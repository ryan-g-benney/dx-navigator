#!/usr/bin/env python3
"""Rule evaluation: counted thresholds, weighted scores, and unknown answers.

Weighted scoring exists because guideline scores are not counts. Two 1.5-point
Wells items are not one 3-point item, and a rule that counted them would refer
a patient the guideline calls unlikely.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "engine"))
from dx_engine.kb import load  # noqa: E402
from dx_engine.rules import fired  # noqa: E402

kb = load(ROOT / "data")
ids = lambda complaint, answers: {r.id for r in fired(kb, complaint, answers)}  # noqa: E731

WELLS = "ng158-pe-wells-table-2"
CRB65 = "ng250-cap-1.2.3"

# Weighted: the threshold is more than 4 points, so 4.0 must not fire.
assert WELLS not in ids("acute-cough", {"clinical_dvt_signs": "present"})  # 3
assert WELLS not in ids("acute-cough", {
    "heart_rate_over_100": "present",      # 1.5
    "recent_immobility": "present",        # 1.5
    "cough_character": "blood_stained"})   # 1  -> 4.0, unlikely
assert WELLS in ids("acute-cough", {
    "clinical_dvt_signs": "present",       # 3
    "pe_alternative_less_likely": "alternative_less_likely"})  # 3 -> 6
assert WELLS in ids("acute-cough", {
    "clinical_dvt_signs": "present",       # 3
    "heart_rate_over_100": "present"})     # 1.5 -> 4.5, likely

# Counting three 1.5s would reach 4.5 and fire; scoring them correctly does not.
assert WELLS not in ids("acute-cough", {
    "heart_rate_over_100": "present", "recent_immobility": "present"})

# The same rule serves both pools PE sits in.
assert WELLS in ids("chest-pain", {
    "clinical_dvt_signs": "present",
    "pe_alternative_less_likely": "alternative_less_likely"})

# Counted: CRB65 refers at two or more, not one.
assert CRB65 not in ids("acute-cough", {"age_years": "sixty_five_or_over"})
assert CRB65 in ids("acute-cough", {
    "age_years": "sixty_five_or_over", "confusion_new": "present"})

# Unknown is not a weak yes.
assert WELLS not in ids("acute-cough", {
    "clinical_dvt_signs": "unknown", "pe_alternative_less_likely": "unknown"})

print(f"rule evaluation ok — kb {kb.version_hash}, {len(kb.rules)} rules")
