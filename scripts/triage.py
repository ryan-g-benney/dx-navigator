#!/usr/bin/env python3
"""Free text in, questions out, ten conditions in their final order.

    triage.py "dry cough for two months, coughing up blood"
    triage.py --auto lung-cancer "dry cough for two months"   answer as that condition
    triage.py --questions 6 "..."                             cap the questioning

The opening description is retrieved through the form contract exactly as
search.py does it. What this adds is the narrowing: pick the symptom that
splits the surviving candidates most evenly, ask about it in plain English,
fold the answer in as one more piece of evidence, and re-rank. Ten narrows to
five narrows to one, and the original ten are printed in their final order.

The tree is built per consultation rather than precomputed. Nothing here is a
reviewable artefact a clinician could sign off; it is the same retrieval
statistics as search.py with more evidence gathered.

WHAT --auto IS NOT. It answers "no" to any symptom the condition's page does
not list, which is not what a patient would say: the NHS page for angina not
mentioning fatigue is silence, not a denial. So --auto over-denies, and it
over-denies most for conditions with the longest symptom lists, since they
offer the most chances to be asked. It is a way to watch the loop run, not a
way to measure it. triage_poc.py --auto has the same bias.

WHAT THE QUESTION CHOICE IS NOT. An even split is the most information one
yes-or-no answer can carry about *this corpus*. It is not the most useful
question to ask a patient, because nothing here knows that a cold is commoner
than lung cancer. Without prevalence the tree will spend a question separating
two equally rare conditions when a GP would not. See the caveat printed at the
end of every run, and "No prevalence" in CLAUDE.md.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import _gemini as G  # noqa: E402
from search import Hit, Match, Retriever  # noqa: E402
from symptom_schema import Record  # noqa: E402

SHORTLIST = [10, 5, 1]   # narrow to each in turn; the first is what retrieval gives
MAX_QUESTIONS = 12       # per narrowing stage, not in total
NO_EVIDENCE = float("-inf")

CAVEAT = """
Retrieval and questioning over corpus statistics, with no prevalence. Questions
are chosen to split this corpus evenly, not by how much a symptom shifts the
odds in a real population, so the order is not a clinical likelihood. Not
clinical advice."""


def next_question(r: Retriever, candidates: list[str], asked: set[int]) -> int | None:
    """The symptom that splits the surviving candidates most evenly.

    An even split is the most information one yes-or-no answer can carry: a
    symptom every candidate lists, or none of them lists, cannot reorder them
    however it is answered. Ties are common once the shortlist is small --
    every symptom exactly half of them list scores the same -- so the rarer
    symptom breaks them, being the one that says more about the corpus at
    large.
    """
    n = len(candidates)
    if n < 2:
        return None
    counts: dict[int, int] = {}
    for slug in candidates:
        for sid in r.links[slug]:
            counts[sid] = counts.get(sid, 0) + 1

    best, best_key = None, (0.0, 0.0)
    for sid, c in counts.items():
        if sid in asked or c == n:
            continue
        p = c / n
        h = -(p * math.log2(p) + (1 - p) * math.log2(1 - p))
        key = (h, r.idf.get(sid, 1.0))
        if key > best_key:
            best, best_key = sid, key
    return best


def question_for(phrase: str, cache: dict[str, str]) -> str:
    if phrase not in cache:
        cache[phrase] = G.ask(
            "Write one short plain-English question a UK GP receptionist could ask "
            f"a patient to find out whether they have this symptom: '{phrase}'. "
            "Reply with the question only.").strip().strip('"')
    return cache[phrase]


def run(r: Retriever, opening: str, answer, verbose: bool = True) -> list[Hit]:
    """Retrieve on the opening, then question until the shortlist stops shrinking.

    `answer(sid, question) -> bool | None` supplies the reply; None means the
    patient did not know, which is folded in as no evidence either way rather
    than as a denial.
    """
    records = r.normalise(opening)
    if verbose:
        print("normalised:")
        for rec in records:
            print(f"  {rec.core_phrase}")

    matches = r.match(records)
    if not matches:
        if verbose:
            print("\nnothing in the description matched the symptom vocabulary")
            print(CAVEAT)
        return []

    opening_hits = r.rank(matches, n=SHORTLIST[0])
    cand = [h.slug for h in opening_hits]
    asked = {m.symptom_id for m in matches}
    cache: dict[str, str] = {}
    score = {h.slug: h.score for h in opening_hits}

    if verbose:
        print(f"\nTop {len(cand)} before any question:")
        for i, h in enumerate(opening_hits, 1):
            print(f"  {i:2d}. {h.score:+.3f}  {h.slug}")

    for target in SHORTLIST[1:]:
        for _ in range(MAX_QUESTIONS):
            if len(cand) <= target:
                break
            sid = next_question(r, cand, asked)
            if sid is None:
                break
            asked.add(sid)
            reply = answer(sid, question_for(r.phrases[sid], cache))
            if reply is not None:
                # A fresh Record per answer: rank() credits one statement to a
                # condition once, keyed on the record's identity, so reusing an
                # object here would silently merge two answers into one.
                matches.append(Match(sid, Record(concept=r.phrases[sid],
                                                 polarity="present" if reply else "absent"),
                                     1.0))
            ranked = r.rank(matches, n=len(r.links))
            score = {h.slug: h.score for h in ranked}
            # Drop at most two per question. A single answer reordering the
            # shortlist is not grounds to discard the rest of it.
            cand = sorted(cand, key=lambda s: -score.get(s, NO_EVIDENCE))[
                :max(target, len(cand) - 2)]
        if verbose:
            print(f"\nNarrowed to {len(cand)}:")
            for slug in cand:
                print(f"  {score.get(slug, 0.0):+.3f}  {slug}")

    final = sorted(opening_hits, key=lambda h: -score.get(h.slug, NO_EVIDENCE))
    if verbose:
        print("\nOriginal ten, final order:")
        for i, h in enumerate(final, 1):
            print(f"  {i:2d}. {score.get(h.slug, 0.0):+.3f}  {h.slug}")
        print(CAVEAT)
    return final


def main() -> None:
    argv = sys.argv[1:]
    auto = None
    limit = MAX_QUESTIONS
    if "--auto" in argv:
        i = argv.index("--auto")
        auto = argv[i + 1]
        del argv[i:i + 2]
    if "--questions" in argv:
        i = argv.index("--questions")
        limit = int(argv[i + 1])
        del argv[i:i + 2]
    text = [a for a in argv if not a.startswith("--")]
    if not text:
        raise SystemExit('usage: triage.py [--auto SLUG] [--questions N] '
                         '"free text describing the symptoms"')

    r = Retriever()
    budget = [limit]

    if auto:
        if auto not in r.links:
            raise SystemExit(f"no condition {auto!r} in the vocabulary")
        has = set(r.links[auto])

        def answer(sid: int, q: str) -> bool | None:
            if budget[0] <= 0:
                return None
            budget[0] -= 1
            reply = sid in has
            print(f"\n  Q: {q}\n  A: {'yes' if reply else 'no'}  (as {auto} would)")
            return reply
    else:
        def answer(sid: int, q: str) -> bool | None:
            if budget[0] <= 0:
                return None
            budget[0] -= 1
            said = input(f"\n  {q} [y/n/?] ").strip().lower()
            return {"y": True, "yes": True, "n": False, "no": False}.get(said)

    run(r, text[0], answer)


if __name__ == "__main__":
    main()
