#!/usr/bin/env python3
"""Self-check for retrieval scoring. Stubs the model; no network.
Run: uv run python scripts/test_search.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from search import LENGTH_ALPHA, Match, Retriever  # noqa: E402
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
    # Two conditions, each matched on exactly one symptom, so they genuinely
    # compete: lung-cancer's symptom is rare (idf 3.0) and common-cold's is
    # common (idf 1.0). Cosine alone favours common-cold (0.95 > 0.90) --
    # only the idf weighting flips the order. Drop idf (set both to 1.0) and
    # this assertion fails, so it is testing the weighting, not the fixture.
    r = Retriever.__new__(Retriever)
    r.phrases = ["blood-stained sputum", "cough"]
    r.links = {
        "lung-cancer": {0: Record(concept="sputum", character="blood-stained")},
        "common-cold": {1: Record(concept="cough")},
    }
    r.idf = {0: 3.0, 1: 1.0}
    hits = r.rank([Match(0, Record(concept="sputum", character="blood-stained"), 0.90),
                   Match(1, Record(concept="cough"), 0.95)])
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


def test_one_statement_credited_once_despite_near_duplicate_rows():
    # "cough" and "coughing" are separate vocabulary rows both linked to
    # lung-cancer; one patient statement about coughing can match both. That
    # is one fact, not two, so it should credit lung-cancer at its stronger
    # weight only -- not the sum of both near-duplicate hits.
    r = Retriever.__new__(Retriever)
    r.phrases = ["cough", "coughing"]
    r.links = {"lung-cancer": {0: Record(concept="cough"), 1: Record(concept="cough")}}
    r.idf = {0: 1.0, 1: 1.5}
    patient = Record(concept="cough")
    weak, strong = r.idf[0] * 0.95, r.idf[1] * 0.90  # 0.95 vs 1.35
    hit = r.rank([Match(0, patient, 0.95), Match(1, patient, 0.90)])[0]
    assert len(hit.evidence) == 1, hit.evidence
    phrase, w = hit.evidence[0]
    assert phrase == "coughing", hit.evidence
    assert abs(w - strong) < 1e-9, (w, strong)
    length = (r.idf[0] + r.idf[1]) ** LENGTH_ALPHA
    assert abs(hit.score - strong / length) < 1e-9, hit.score
    assert hit.score != (weak + strong) / length, "credited both hits instead of the strongest"


for fn in (test_rare_symptom_outweighs_common_one, test_absent_symptom_argues_against,
           test_duration_mismatch_reduces_but_never_reverses, test_evidence_names_the_phrases,
           test_one_statement_credited_once_despite_near_duplicate_rows):
    fn()
    print(f"  ok  {fn.__name__}")
print("search: all checks passed")
