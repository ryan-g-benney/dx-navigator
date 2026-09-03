#!/usr/bin/env python3
"""Self-check for the symptom form contract. Run: uv run python scripts/test_symptom_schema.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from symptom_schema import (  # noqa: E402
    DURATIONS, ONSETS, FACET_FLOOR, Record, band_distance, facet_multiplier, validate,
)


def rejects(fn, why: str) -> None:
    try:
        fn()
    except ValueError:
        return
    raise AssertionError(f"should have been rejected: {why}")


def test_core_phrase():
    assert Record(concept="chest pain").core_phrase == "chest pain"
    assert Record(concept="sputum", character="blood-stained").core_phrase == "blood-stained sputum"
    assert Record(concept="numbness", site="hand").core_phrase == "numbness in the hand"
    assert (Record(concept="pain", character="crushing", site="chest").core_phrase
            == "crushing pain in the chest")


def test_form_rules():
    validate(Record(concept="chest pain", character="crushing", site="lower back"))
    rejects(lambda: validate(Record(concept="confusion and slurred speech")),
            "two concepts in one record")
    rejects(lambda: validate(Record(concept="vision loss or blurring")), "or in the concept")
    rejects(lambda: validate(Record(concept="Chest Pain")), "not lower case")
    rejects(lambda: validate(Record(concept="you feel sick")), "second person")
    rejects(lambda: validate(Record(concept="pain", character="crushing tearing")),
            "character must be one word")
    rejects(lambda: validate(Record(concept="respiratory tract symptoms of infection")),
            "concept over two words")
    rejects(lambda: validate(Record(concept="cough", duration="two months")),
            "duration not a band token")
    rejects(lambda: validate(Record(concept="cough", polarity="maybe")), "polarity not a token")


def test_band_distance():
    # unspecified on either side is a no-op, never a mismatch
    assert band_distance("unspecified", "over_8_weeks", DURATIONS) is None
    assert band_distance("hours", "unspecified", ONSETS) is None
    assert band_distance("hours", "hours", ONSETS) == 0.0
    assert band_distance("under_1_day", "over_8_weeks", DURATIONS) == 1.0
    near = band_distance("one_to_3_weeks", "three_to_8_weeks", DURATIONS)
    far = band_distance("under_1_day", "three_to_8_weeks", DURATIONS)
    assert 0.0 < near < far < 1.0


def test_facet_multiplier():
    cough = Record(concept="cough")
    chronic = Record(concept="cough", duration="over_8_weeks")
    acute = Record(concept="cough", duration="under_1_day")
    assert facet_multiplier(cough, chronic) == 1.0            # corpus silent, no penalty
    assert facet_multiplier(chronic, chronic) == 1.0
    assert facet_multiplier(chronic, acute) == FACET_FLOOR    # opposite ends, floored
    assert 0 < FACET_FLOOR < 1
    mid = facet_multiplier(chronic, Record(concept="cough", duration="three_to_8_weeks"))
    assert FACET_FLOOR < mid < 1.0                            # a mismatch is never negative


for fn in (test_core_phrase, test_form_rules, test_band_distance, test_facet_multiplier):
    fn()
    print(f"  ok  {fn.__name__}")
print("symptom schema: all checks passed")
