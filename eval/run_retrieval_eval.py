#!/usr/bin/env python3
"""Does the form contract retrieve better than the string bank it replaces?

    run_retrieval_eval.py --held-out 150    seed a condition on its own symptoms
    run_retrieval_eval.py --bank 150        the same, on the v1 bank, for comparison
    run_retrieval_eval.py --paraphrase 200  rewrite a symptom as a patient would

Held-out seeds on the two COMMONEST symptoms, not the rarest. Seeding on the
rarest flatters the score: a symptom two conditions share nearly names the
answer. The commonest is how a patient actually opens.
"""
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import _gemini as G  # noqa: E402
from search import CAND, Match, Retriever  # noqa: E402
from symptom_schema import GEMINI_SCHEMA, Record  # noqa: E402

BANNER = """
{bar}
!  Corpus, paraphrases and extraction all come from one scrape and one model.
!  These are retrieval and internal-consistency figures. They are NOT evidence
!  that the knowledge base is clinically correct.
{bar}"""


def _pool(r: Retriever, n: int, shared_with: Retriever | None = None) -> list[str]:
    """The conditions to seed on: at least three symptoms, same seed every run.

    When a second system is given, only conditions both can retrieve are kept,
    so two rows of the table are scored over the identical 150 and a difference
    between them is about the ranking rather than about which pages survived
    each scrape.
    """
    pool = [c for c, s in r.links.items() if len(s) >= 3]
    if shared_with is not None:
        both = {c for c, s in shared_with.links.items() if len(s) >= 3}
        pool = [c for c in pool if c in both]
    random.seed(0)
    return random.sample(pool, min(n, len(pool)))


def _seed(r: Retriever, slug: str, target: float | None = None) -> list[int]:
    """The two symptoms to open on: the commonest, or the closest to a target.

    Commonest is how a patient opens, and is what the table reports. The target
    form exists for one control: the two vocabularies merge differently, so
    each system's own commonest symptom is shared by a different number of
    conditions, and a system whose vocabulary merged harder is being asked a
    harder question. Passing the other system's inverse document frequency
    asks both the same one.
    """
    sids = list(r.links[slug])
    if target is None:
        return sorted(sids, key=lambda s: r.idf.get(s, 1.0))[:2]
    return sorted(sids, key=lambda s: abs(r.idf.get(s, 1.0) - target))[:2]


def _score(r: Retriever, picks: list[str], label: str,
           targets: dict[str, float] | None = None) -> None:
    top1 = top5 = top10 = 0
    for k, slug in enumerate(picks, 1):
        sids = _seed(r, slug, targets.get(slug) if targets else None)
        matches = [Match(s, Record(concept="x"), 1.0) for s in sids]
        order = [h.slug for h in r.rank(matches, n=10)]
        pos = order.index(slug) + 1 if slug in order else None
        top1 += pos == 1
        top5 += bool(pos and pos <= 5)
        top10 += bool(pos)
        print(f"  {k}/{len(picks)} {slug:38s} rank {pos or '>10'}", flush=True)
    t = len(picks)
    print(f"\n{label}, {t} conditions: top-1 {top1/t:.0%}  "
          f"top-5 {top5/t:.0%}  top-10 {top10/t:.0%}")
    print(BANNER.format(bar="!" * 72))


def held_out(r: Retriever, n: int) -> None:
    _score(r, _pool(r, n), "held-out")


def bank_retriever() -> Retriever:
    """The v1 string bank behind the same interface, so the same scorer reads it.

    The 75/85/85 in triage_poc.py cannot be compared with the v2 row: it was
    measured before rank() stopped crediting one patient statement several
    times to the same condition, and triage_poc scores in its own way. This
    rebuilds the bank under today's scorer. There are no facets in v1, so every
    record is unspecified and facet_multiplier returns 1.0 throughout.
    """
    b = Retriever.__new__(Retriever)
    rows = (CAND / "symptom-bank.tsv").read_text().splitlines()[1:]
    b.phrases = [""] * (max(int(ln.split("\t")[0]) for ln in rows if ln) + 1)
    for ln in rows:
        if ln:
            sid, canonical = ln.split("\t")[:2]
            b.phrases[int(sid)] = canonical
    b.index = None
    b.links = {}
    for ln in (CAND / "condition-symptoms.tsv").read_text().splitlines()[1:]:
        if ln:
            cond, sid = ln.split("\t")[:2]
            b.links.setdefault(cond, {})[int(sid)] = Record(concept="x")
    n = len(b.links)
    seen: dict[int, int] = {}
    for sids in b.links.values():
        for sid in sids:
            seen[sid] = seen.get(sid, 0) + 1
    b.idf = {sid: math.log((n + 1) / (c + 1)) + 1.0 for sid, c in seen.items()}
    return b


def bank(r: Retriever, n: int) -> None:
    """Both systems over the identical conditions, under the identical scorer."""
    b = bank_retriever()
    picks = _pool(b, n, shared_with=r)
    print(f"{len(picks)} conditions retrievable by both systems\n")
    print("--- v1 string bank ---")
    _score(b, picks, "string bank")
    print("\n--- v2 form contract ---")
    _score(r, picks, "form contract")

    # Same conditions, same scorer, and now the same question: seed v2 on the
    # symptoms whose corpus frequency matches what the bank opened on, so the
    # two rows differ by the ranking rather than by how generic each system's
    # own commonest symptom happens to be.
    targets = {slug: sum(b.idf.get(s, 1.0) for s in _seed(b, slug)) / 2 for slug in picks}
    print("\n--- v2 form contract, seeded at the bank's symptom frequency ---")
    _score(r, picks, "form contract (frequency-matched)", targets=targets)


PARA_PROMPT = ("Rewrite this symptom the way a UK patient would describe it to a "
               "receptionist. One sentence, their words, no medical terms.\n\nSymptom: ")


def paraphrase(r: Retriever, n: int) -> None:
    """Two figures, because exact recovery understates what retrieval needs.

    Exact asks whether the paraphrase came back to the row it was written from.
    Same-condition asks whether it came back to a row carrying the same
    conditions, which is what the ranking actually consumes: the vocabulary
    holds near-duplicates ("tiredness" beside "daytime tiredness"), and landing
    on the sibling loses nothing downstream. Exact is the floor, same-condition
    the ceiling, and the truth for a differential is the second.
    """
    carriers: dict[int, set[str]] = {}
    for slug, sids in r.links.items():
        for sid in sids:
            carriers.setdefault(sid, set()).add(slug)

    random.seed(0)
    picks = random.sample(range(len(r.phrases)), min(n, len(r.phrases)))
    hit = same = 0
    for k, sid in enumerate(picks, 1):
        said = G.ask(PARA_PROMPT + r.phrases[sid]).strip()
        got = {m.symptom_id for m in r.match(r.normalise(said))}
        ok = sid in got
        shared = carriers.get(sid, set()) & {c for g in got for c in carriers.get(g, set())}
        hit += ok
        same += bool(shared)
        tag = "ok  " if ok else ("sib " if shared else "MISS")
        print(f"  {k}/{len(picks)} {tag} {r.phrases[sid]:34s} <- {said}", flush=True)
    t = len(picks)
    print(f"\nparaphrase recovery: exact {hit/t:.0%}, same-condition {same/t:.0%}, of {t}")
    print(BANNER.format(bar="!" * 72))


def dense(r: Retriever, n: int) -> None:
    """One vector per condition, from its joined symptom profile."""
    import numpy as np

    import vector_index as V

    slugs = sorted(r.links)
    profiles = [", ".join(r.phrases[s] for s in sorted(r.links[slug])) for slug in slugs]
    index = V.from_vectors(np.array(G.embed(profiles, progress=True), dtype="float32"))

    random.seed(0)                      # same seed, same picks as held_out
    pool = [c for c, s in r.links.items() if len(s) >= 3]
    picks = random.sample(pool, min(n, len(pool)))
    top1 = top5 = top10 = 0
    for k, slug in enumerate(picks, 1):
        sids = sorted(r.links[slug], key=lambda s: r.idf.get(s, 1.0))[:2]
        seed = ", ".join(r.phrases[s] for s in sids)
        vec = np.array(G.embed([seed]), dtype="float32")
        order = [slugs[i] for i, _ in V.search(index, vec, k=10)[0]]
        pos = order.index(slug) + 1 if slug in order else None
        top1 += pos == 1
        top5 += bool(pos and pos <= 5)
        top10 += bool(pos)
        print(f"  {k}/{len(picks)} {slug:38s} rank {pos or '>10'}", flush=True)
    t = len(picks)
    print(f"\ndense control, {t} conditions: top-1 {top1/t:.0%}  "
          f"top-5 {top5/t:.0%}  top-10 {top10/t:.0%}")
    print(BANNER.format(bar="!" * 72))


def main() -> None:
    a = sys.argv
    r = Retriever()
    if "--held-out" in a:
        held_out(r, int(a[a.index("--held-out") + 1]))
    elif "--paraphrase" in a:
        paraphrase(r, int(a[a.index("--paraphrase") + 1]))
    elif "--bank" in a:
        bank(r, int(a[a.index("--bank") + 1]))
    elif "--dense" in a:
        dense(r, int(a[a.index("--dense") + 1]))
    else:
        raise SystemExit("give --held-out N, --bank N, --paraphrase N or --dense N")


if __name__ == "__main__":
    main()
