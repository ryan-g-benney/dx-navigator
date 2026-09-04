#!/usr/bin/env python3
"""Checks on the questioning, which is the part that can be wrong quietly.

A question chooser that picks a symptom every candidate shares still returns a
question, still gets an answer, and narrows nothing. These four assertions are
the smallest things that fail if the narrowing stops working.

    uv run --no-sync python scripts/test_triage.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from search import Match, Retriever  # noqa: E402
from symptom_schema import Record  # noqa: E402
from triage import next_question  # noqa: E402


def fake(links: dict[str, list[int]], idf: dict[int, float] | None = None) -> Retriever:
    r = Retriever.__new__(Retriever)
    r.links = {c: {s: Record(concept="x") for s in sids} for c, sids in links.items()}
    r.phrases = [f"symptom {i}" for i in range(20)]
    r.idf = idf or {s: 1.0 for sids in links.values() for s in sids}
    return r


def test_picks_the_symptom_that_splits_evenly() -> None:
    # 1 is in every candidate and cannot reorder them; 2 is in half
    r = fake({"a": [1, 2], "b": [1, 2], "c": [1, 3], "d": [1, 3]})
    assert next_question(r, ["a", "b", "c", "d"], asked=set()) == 2


def test_never_asks_twice_and_never_asks_the_useless() -> None:
    r = fake({"a": [1, 2], "b": [1, 2], "c": [1, 3], "d": [1, 3]})
    # with 2 asked, 3 is the only remaining splitter; 1 is shared by all
    assert next_question(r, ["a", "b", "c", "d"], asked={2}) == 3
    assert next_question(r, ["a", "b", "c", "d"], asked={2, 3}) is None
    # a single candidate cannot be split
    assert next_question(r, ["a"], asked=set()) is None


def test_ties_break_towards_the_rarer_symptom() -> None:
    # 2 and 3 both split the four candidates evenly; 3 is rarer in the corpus
    r = fake({"a": [2, 3], "b": [2, 3], "c": [4], "d": [4]},
             idf={2: 1.0, 3: 5.0, 4: 1.0})
    assert next_question(r, ["a", "b", "c", "d"], asked=set()) == 3


def test_a_denial_demotes_the_condition_that_lists_it() -> None:
    r = fake({"a": [1, 2], "b": [1, 3]})
    said = Record(concept="symptom 1")
    denied = Record(concept="symptom 2", polarity="absent")
    before = {h.slug: h.score for h in r.rank([Match(1, said, 1.0)], n=10)}
    after = {h.slug: h.score for h in
             r.rank([Match(1, said, 1.0), Match(2, denied, 1.0)], n=10)}
    assert before["a"] == before["b"], before
    assert after["a"] < after["b"], after          # only a lists the denied symptom
    assert after["b"] == before["b"], "b has no evidence about symptom 2"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"  ok  {name}")
    print("4/4 checks pass")
