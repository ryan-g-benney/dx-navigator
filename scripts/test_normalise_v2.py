#!/usr/bin/env python3
"""One focused check: _record() must not crash on explicit JSON nulls.

The flash model can emit `null` for any field not in the schema's `required`
list (character, site, duration_text, and the band fields default there too
if the model omits a value it isn't sure of). raw.get(field, default) does
NOT catch this -- an explicit null still returns None, not the default. Run
directly: python scripts/test_normalise_v2.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from normalise_v2 import _record  # noqa: E402


def test_record_tolerates_null_optional_fields() -> None:
    raw = {
        "id": 1,
        "concept": "cough",
        "character": None,
        "site": None,
        "onset": None,
        "duration": None,
        "duration_text": None,
        "severity": None,
        "progression": None,
        "polarity": "present",
    }
    r = _record(raw)
    assert r is not None, "_record() dropped a valid record instead of defaulting nulls"
    assert r.concept == "cough"
    assert r.character == ""
    assert r.site == ""
    assert r.onset == "unspecified"
    assert r.duration == "unspecified"
    assert r.duration_text == ""
    assert r.severity == "unspecified"
    assert r.progression == "unspecified"


def test_record_tolerates_missing_optional_fields() -> None:
    # Belt and braces: absent keys must still default the same way.
    r = _record({"id": 2, "concept": "nausea", "polarity": "present"})
    assert r is not None
    assert r.character == ""
    assert r.onset == "unspecified"


if __name__ == "__main__":
    test_record_tolerates_null_optional_fields()
    test_record_tolerates_missing_optional_fields()
    print("ok")
