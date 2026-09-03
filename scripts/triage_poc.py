#!/usr/bin/env python3
"""Proof of concept: free-text symptoms in, ranked conditions out, questions between.

The loop is the one asked for. Free text is read by a flash model into symptom
phrases, those are matched to the canonical bank by embedding cosine, and the
conditions are ranked by cosine in symptom space. The tool then looks for the
symptom that most evenly splits the surviving candidates, asks about it in
plain English, folds the answer in, and re-ranks. Ten narrows to five narrows
to one, and the original ten are printed in their final order.

Weighting is inverse document frequency, not clinical judgement. A symptom
that half the corpus lists carries almost no weight and a symptom two
conditions list carries a lot. That is a corpus statistic standing in for a
likelihood ratio -- it fixes "cough counts the same as coughing blood", which
flat matching could not, but it is not a published figure and must not be read
as one. Prevalence is still absent, so the ranking has no prior.

    triage_poc.py --case "dry cough for two months, coughing blood, losing weight"
    triage_poc.py --auto lung-cancer          answer as that condition would
    triage_poc.py --eval 60                   accuracy over 60 random conditions
    triage_poc.py                             interactive
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import _gemini as G  # noqa: E402

BANK = ROOT / "data" / "candidates" / "symptom-bank.tsv"
LINKS = ROOT / "data" / "candidates" / "condition-symptoms.tsv"
CONDITIONS = ROOT / "data" / "candidates" / "conditions.tsv"

MATCH = 0.80        # cosine below this is not the same symptom
SHORTLIST = [10, 5, 1]
MAX_QUESTIONS = 12
ABSENT_WEIGHT = 0.7  # a denied symptom argues less than a reported one
# Plain cosine divides by the condition's full vector length, which hands an
# advantage to whatever has fewest symptoms: silicosis, listed with three
# generic ones, outranked lung cancer listed with ten. Dividing by the length
# raised to a power below one damps that without swinging the other way, where
# an unnormalised dot product would simply favour the longest list.
#
# Measured over 150 held-out conditions opened on their two commonest symptoms:
#
#   alpha   top-1  top-5  top-10
#   1.00     63%    73%    73%      full cosine, the short-vector bias
#   0.50     74%    84%    84%
#   0.25     75%    85%    85%
#   0.00     77%    83%    83%      no length normalisation at all
#
# Full normalisation is clearly worse. Everything from 0 to 0.5 is within the
# standard error of about 3.5 points, so 0.25 is chosen for sitting in the
# middle of the indistinguishable range rather than for beating the others.
LENGTH_ALPHA = 0.25

EXTRACT = {
    "type": "object",
    "properties": {"symptoms": {"type": "array", "items": {"type": "string"}}},
    "required": ["symptoms"],
}


class Corpus:
    def __init__(self) -> None:
        rows = [ln.split("\t") for ln in BANK.read_text().splitlines()[1:] if ln]
        self.names = [r[1] for r in rows]
        links = [ln.split("\t") for ln in LINKS.read_text().splitlines()[1:] if ln]
        self.conds = sorted({c for c, _ in links})
        ci = {c: i for i, c in enumerate(self.conds)}
        self.display = {r[0]: r[1] for r in
                        (ln.split("\t") for ln in CONDITIONS.read_text().splitlines()[1:])
                        if len(r) > 1}

        self.has = np.zeros((len(self.conds), len(self.names)), dtype=bool)
        for c, s in links:
            self.has[ci[c], int(s)] = True

        n = len(self.conds)
        df = self.has.sum(axis=0)
        # +1 on both sides so a symptom every condition lists scores near zero
        # rather than exactly zero, and a symptom none lists cannot divide.
        self.idf = np.log((n + 1) / (df + 1)) + 1.0
        self.mat = self.has * self.idf
        norms = np.linalg.norm(self.mat, axis=1)
        self.set_alpha(LENGTH_ALPHA)

        vecs = np.array(G.embed(self.names), dtype=np.float32)
        self.svec = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)

    def set_alpha(self, alpha: float) -> None:
        norms = np.linalg.norm(self.mat, axis=1)
        self.unit = self.mat / np.where(norms == 0, 1, norms ** alpha)[:, None]

    def match(self, phrases: list[str]) -> list[tuple[int, str, float]]:
        """Nearest canonical symptom for each free-text phrase."""
        if not phrases:
            return []
        q = np.array(G.embed(phrases), dtype=np.float32)
        q /= np.linalg.norm(q, axis=1, keepdims=True)
        out = []
        for phrase, sims in zip(phrases, q @ self.svec.T):
            i = int(np.argmax(sims))
            if sims[i] >= MATCH:
                out.append((i, phrase, float(sims[i])))
        return out

    def rank(self, evidence: dict[int, int]) -> np.ndarray:
        q = np.zeros(len(self.names))
        for sid, val in evidence.items():
            q[sid] = self.idf[sid] * (1.0 if val > 0 else -ABSENT_WEIGHT)
        norm = np.linalg.norm(q)
        return self.unit @ q / (norm if norm else 1)


def extract(text: str) -> list[str]:
    res = G.ask(
        "Split this UK patient's description into separate symptoms. One short "
        "phrase per symptom, lower case, no second person, keep duration and "
        "character when stated. Ignore anything that is not a symptom.\n\n"
        f"Description: {text}", schema=EXTRACT)
    return [s.strip() for s in res.get("symptoms", []) if s.strip()]


def next_question(c: Corpus, cand: np.ndarray, asked: set[int]) -> int | None:
    """The symptom that splits the surviving candidates most evenly.

    An even split is the most information one yes-or-no answer can carry: a
    symptom every candidate shares, or none does, cannot change the order
    however it is answered.
    """
    sub = c.has[cand]
    p = sub.mean(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        h = -(p * np.log2(p) + (1 - p) * np.log2(1 - p))
    h = np.nan_to_num(h)
    h[list(asked)] = -1
    return int(np.argmax(h)) if h.max() > 0 else None


def phrase(name: str, cache: dict[str, str]) -> str:
    if name not in cache:
        cache[name] = G.ask(
            "Write one short plain-English question a UK GP receptionist could ask "
            f"a patient to find out whether they have this symptom: '{name}'. "
            "Reply with the question only.").strip().strip('"')
    return cache[name]


def run(c: Corpus, opening: str, answer, verbose: bool = True) -> list[str]:
    evidence: dict[int, int] = {}
    for sid, ph, sim in c.match(extract(opening)):
        evidence[sid] = 1
        if verbose:
            print(f"  '{ph}' -> {c.names[sid]}  (cos {sim:.2f})")

    if not evidence:
        if verbose:
            print("  nothing in the description matched the symptom bank")
        return []

    scores = c.rank(evidence)
    initial = list(np.argsort(-scores)[:SHORTLIST[0]])
    cand = np.array(initial)
    asked: set[int] = set(evidence)
    cache: dict[str, str] = {}

    if verbose:
        print(f"\nTop {len(cand)} before any question:")
        for i in cand:
            print(f"  {scores[i]:+.3f}  {c.display.get(c.conds[i], c.conds[i])}")

    for target in SHORTLIST[1:]:
        for _ in range(MAX_QUESTIONS):
            if len(cand) <= target:
                break
            sid = next_question(c, cand, asked)
            if sid is None:
                break
            asked.add(sid)
            reply = answer(sid, phrase(c.names[sid], cache))
            if reply is not None:
                evidence[sid] = 1 if reply else -1
            scores = c.rank(evidence)
            cand = np.array(sorted(cand, key=lambda i: -scores[i])[:max(target, len(cand) - 2)])
        if verbose:
            print(f"\nNarrowed to {len(cand)}:")
            for i in cand:
                print(f"  {scores[i]:+.3f}  {c.display.get(c.conds[i], c.conds[i])}")

    final = sorted(initial, key=lambda i: -scores[i])
    if verbose:
        print("\nOriginal ten, final order:")
        for rank_, i in enumerate(final, 1):
            print(f"  {rank_:2d}. {scores[i]:+.3f}  {c.display.get(c.conds[i], c.conds[i])}")
    return [c.conds[i] for i in final]


def main() -> None:
    a = sys.argv
    c = Corpus()
    if "--alpha" in a:
        c.set_alpha(float(a[a.index("--alpha") + 1]))

    if "--eval" in a:
        n = int(a[a.index("--eval") + 1])
        hard = "--hard" in a
        random.seed(0)
        pool = [i for i in range(len(c.conds)) if c.has[i].sum() >= 3]
        top1 = top5 = top10 = 0
        picks = random.sample(pool, min(n, len(pool)))
        for k, ti in enumerate(picks, 1):
            mine = np.where(c.has[ti])[0]
            # Seeding on the two rarest symptoms is the easy case and flatters the
            # score: a symptom two conditions share nearly names the answer on its
            # own. --hard seeds on the two commonest instead, which is how a
            # patient actually opens -- "I feel sick and I am tired" -- and tests
            # whether the questions can recover from a generic start.
            seed = sorted(mine, key=lambda s: (1 if hard else -1) * c.idf[s])[:2]
            opening = ", ".join(c.names[s] for s in seed)
            order = run(c, opening, lambda sid, _q: bool(c.has[ti, sid]), verbose=False)
            slug = c.conds[ti]
            top1 += order[:1] == [slug]
            top5 += slug in order[:5]
            top10 += slug in order[:10]
            print(f"  {k}/{len(picks)} {slug:38s} rank "
                  f"{order.index(slug) + 1 if slug in order else '>10'}", flush=True)
        t = len(picks)
        print(f"\n{t} cases: top-1 {top1/t:.0%}  top-5 {top5/t:.0%}  top-10 {top10/t:.0%}")
        return

    if "--auto" in a:
        slug = a[a.index("--auto") + 1]
        ti = c.conds.index(slug)
        mine = np.where(c.has[ti])[0]
        seed = sorted(mine, key=lambda s: -c.idf[s])[:2]
        opening = ", ".join(c.names[s] for s in seed)
        print(f"Simulating {slug}, opening with: {opening}\n")

        def answer(sid: int, q: str) -> bool:
            yes = bool(c.has[ti, sid])
            print(f"\nQ: {q}\nA: {'yes' if yes else 'no'}")
            return yes
        run(c, opening, answer)
        return

    if "--case" in a:
        text = a[a.index("--case") + 1]
        replies = iter(a[a.index("--answers") + 1].split(",")) if "--answers" in a else None

        def answer(sid: int, q: str):
            if replies is not None:
                r = next(replies, "unsure").strip().lower()
            else:
                print(f"\nQ: {q}")
                r = input("A (yes/no/unsure): ").strip().lower()
            print(f"\nQ: {q}\nA: {r}" if replies is not None else "")
            return True if r.startswith("y") else False if r.startswith("n") else None
        run(c, text, answer)
        return

    text = input("Describe the symptoms: ").strip()

    def answer(sid: int, q: str):
        print(f"\nQ: {q}")
        r = input("A (yes/no/unsure): ").strip().lower()
        return True if r.startswith("y") else False if r.startswith("n") else None
    run(c, text, answer)


if __name__ == "__main__":
    main()
