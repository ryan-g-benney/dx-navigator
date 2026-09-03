#!/usr/bin/env python3
"""Self-check for retrieval scoring. Stubs the model; no network.
Run: uv run python scripts/test_search.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from search import Match, Retriever  # noqa: E402
from symptom_schema import Record  # noqa: E402


def fake() -> Retriever:
    r = Retriever.__new__(Retriever)
    r.phrases = ["blood-stained sputum", "cough", "weight loss"]
    r.links = {                       # condition -> symptom_id -> corpus record
        "lung-cancer": {0: Record(concept="sputum", character="blood-stained"),
                        1: Record(concept="cough", duration="over_8_weeks"),
                        2: Record(concept="weight loss")},
        "common-cold": {1: Record(concept="cough", duration="one_to_7_days")},
    }
    r.idf = {0: 3.0, 1: 1.0, 2: 3.0}  # cough is common, so it says little
    return r


def test_rare_symptom_outweighs_common_one():
    r = fake()
    hits = r.rank([Match(0, Record(concept="sputum", character="blood-stained"), 0.95)])
    assert hits[0].slug == "lung-cancer", hits
    assert hits[0].score > 0


def test_absent_symptom_argues_against():
    r = fake()
    present = r.rank([Match(2, Record(concept="weight loss"), 0.99)])[0].score
    absent = r.rank([Match(2, Record(concept="weight loss", polarity="absent"), 0.99)])
    assert absent[0].score < 0 < present, (absent, present)


def test_duration_mismatch_reduces_but_never_reverses():
    r = fake()
    chronic = Record(concept="cough", duration="over_8_weeks")
    acute = Record(concept="cough", duration="under_1_day")
    agree = r.rank([Match(1, chronic, 0.99)])
    clash = r.rank([Match(1, acute, 0.99)])
    lung_agree = next(h.score for h in agree if h.slug == "lung-cancer")
    lung_clash = next(h.score for h in clash if h.slug == "lung-cancer")
    assert 0 < lung_clash < lung_agree, (lung_clash, lung_agree)


def test_evidence_names_the_phrases():
    r = fake()
    hit = r.rank([Match(0, Record(concept="sputum", character="blood-stained"), 0.95)])[0]
    assert [p for p, _ in hit.evidence] == ["blood-stained sputum"], hit.evidence


for fn in (test_rare_symptom_outweighs_common_one, test_absent_symptom_argues_against,
           test_duration_mismatch_reduces_but_never_reverses, test_evidence_names_the_phrases):
    fn()
    print(f"  ok  {fn.__name__}")
print("search: all checks passed")
