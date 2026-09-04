#!/usr/bin/env python3
"""Checks that the two dataset views stay the same shape and read the right files.

Selecting the wrong table is a silent failure: the frames still build, the
summary still prints, and every number in it is about the other vocabulary.

    uv run --no-sync python scripts/test_dataset.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from dataset import CAND, frames  # noqa: E402


def rows(path: Path) -> int:
    return len([ln for ln in path.read_text().splitlines()[1:] if ln])


def test_both_views_have_the_same_columns() -> None:
    a, b = frames(), frames(v2=True)
    for name in ("conditions", "symptoms", "links"):
        extra = set(b[name].columns) - set(a[name].columns)
        missing = set(a[name].columns) - set(b[name].columns)
        # v2 carries the parsed character/concept/site the bank never had
        assert not missing, (name, missing)
        assert extra <= {"character", "concept", "site"}, (name, extra)


def test_each_view_reads_its_own_tables() -> None:
    a, b = frames(), frames(v2=True)
    assert len(a["links"]) == rows(CAND / "condition-symptoms.tsv"), len(a["links"])
    assert len(b["links"]) == rows(CAND / "condition-symptoms-v2.tsv"), len(b["links"])
    assert len(a["symptoms"]) == rows(CAND / "symptom-bank.tsv")
    assert len(b["symptoms"]) == rows(CAND / "symptoms-v2.tsv")
    assert len(a["links"]) != len(b["links"]), "the two views returned the same table"


def test_idf_is_the_weight_the_scorer_uses() -> None:
    import math
    b = frames(v2=True)
    n = b["links"]["condition"].nunique()
    row = b["symptoms"].iloc[0]
    assert abs(row["idf"] - (math.log((n + 1) / (row["n_conditions"] + 1)) + 1.0)) < 1e-9


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"  ok  {name}")
    print("3/3 checks pass")
