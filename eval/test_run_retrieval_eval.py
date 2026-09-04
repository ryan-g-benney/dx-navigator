#!/usr/bin/env python3
"""Checks on the parts of the eval that could be wrong without looking wrong.

A scoring harness that silently seeds on the wrong symptoms, or builds the
baseline from the wrong table, reports a number rather than an error. These
four assertions are the smallest things that fail if it does.

    uv run --no-sync python eval/test_run_retrieval_eval.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "scripts"))

from run_retrieval_eval import _pool, _seed, bank_retriever  # noqa: E402
from search import Retriever  # noqa: E402
from symptom_schema import Record  # noqa: E402


def fake(links: dict[str, list[int]], idf: dict[int, float]) -> Retriever:
    r = Retriever.__new__(Retriever)
    r.links = {c: {s: Record(concept="x") for s in sids} for c, sids in links.items()}
    r.idf = idf
    r.phrases = [f"p{i}" for i in range(10)]
    return r


def test_seed_takes_the_commonest_two() -> None:
    # lowest inverse document frequency is the commonest symptom
    r = fake({"a": [1, 2, 3]}, {1: 5.0, 2: 0.5, 3: 1.0})
    assert _seed(r, "a") == [2, 3], _seed(r, "a")


def test_seed_with_a_target_takes_the_closest_two() -> None:
    r = fake({"a": [1, 2, 3]}, {1: 5.0, 2: 0.5, 3: 1.0})
    # asked for 4.8, the commonest pair is the wrong answer
    assert _seed(r, "a", target=4.8) == [1, 3], _seed(r, "a", target=4.8)


def test_pool_keeps_only_conditions_both_systems_can_retrieve() -> None:
    a = fake({"x": [1, 2, 3], "y": [1, 2, 3], "z": [1, 2, 3]}, {})
    b = fake({"x": [1, 2, 3], "y": [1, 2]}, {})       # y has too few, z is absent
    assert _pool(a, 10, shared_with=b) == ["x"], _pool(a, 10, shared_with=b)


def test_bank_retriever_reads_v1_and_not_v2() -> None:
    b = bank_retriever()
    rows = (ROOT / "data/candidates/condition-symptoms.tsv").read_text().splitlines()[1:]
    assert len(b.links) == len({ln.split("\t")[0] for ln in rows if ln}), len(b.links)
    assert sum(len(s) for s in b.links.values()) == len([ln for ln in rows if ln])
    # phrases are the bank's canonical strings, indexed by symptom id
    first = (ROOT / "data/candidates/symptom-bank.tsv").read_text().splitlines()[1]
    sid, canonical = first.split("\t")[:2]
    assert b.phrases[int(sid)] == canonical, b.phrases[int(sid)]
    # every linked symptom carries a weight, or rank() silently falls back to 1.0
    assert all(s in b.idf for sids in b.links.values() for s in sids)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"  ok  {name}")
    print("4/4 checks pass")
