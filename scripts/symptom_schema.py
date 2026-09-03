#!/usr/bin/env python3
"""The symptom form contract: how a symptom is written, and how two are compared.

The schema fixes the SHAPE of a symptom, not a list of permitted symptoms.
Comparison is by embedding cosine, and what makes two phrasings of one symptom
land together is a shared grammar and register, not a shared enumeration.

Only `core_phrase` is embedded. Onset, duration, severity, progression and
polarity are compared arithmetically, for two reasons that are properties of
embeddings rather than preferences:

  - negation does not embed. "no fever" sits near 0.9 cosine from "fever".
  - time dominates a short string. In "chest pain for three weeks" the duration
    is half the tokens.

Prose rules and worked examples: docs/symptom-schema.md
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Ordered. `unspecified` is last and is excluded from distance.
DURATIONS = ["under_1_day", "one_to_7_days", "one_to_3_weeks",
             "three_to_8_weeks", "over_8_weeks", "unspecified"]
# Verbatim from data/shared/variables.yaml, so both tracks share one vocabulary.
ONSETS = ["seconds_to_minutes", "hours", "days", "weeks_or_longer", "unspecified"]
SEVERITIES = ["mild", "moderate", "severe", "unspecified"]
PROGRESSIONS = ["improving", "stable", "worsening", "unspecified"]
POLARITIES = ["present", "absent"]

# A facet mismatch is weaker evidence, never counter-evidence, so the
# multiplier is floored above zero and never goes negative.
# ponytail: 0.4 is a guess; fit it against the paraphrase eval.
FACET_FLOOR = 0.4

BANNED = (" and ", " or ", " with ", "you ", "your ", " a bit ", " sometimes ")


@dataclass(frozen=True)
class Record:
    """One symptom, one concept. Bundles are split before they get here."""

    concept: str
    character: str = ""
    site: str = ""
    onset: str = "unspecified"
    duration: str = "unspecified"
    duration_text: str = ""
    severity: str = "unspecified"
    progression: str = "unspecified"
    polarity: str = "present"

    @property
    def core_phrase(self) -> str:
        head = " ".join(p for p in (self.character, self.concept) if p)
        return f"{head} in the {self.site}" if self.site else head


def validate(r: Record) -> None:
    """Raise ValueError on anything the contract forbids."""
    for name, value, order in (("onset", r.onset, ONSETS),
                               ("duration", r.duration, DURATIONS),
                               ("severity", r.severity, SEVERITIES),
                               ("progression", r.progression, PROGRESSIONS),
                               ("polarity", r.polarity, POLARITIES)):
        if value not in order:
            raise ValueError(f"{name}={value!r} is not one of {order}")

    for slot in ("concept", "character", "site"):
        text = getattr(r, slot)
        if text != text.lower():
            raise ValueError(f"{slot}={text!r} must be lower case")
        if any(b in f" {text} " for b in BANNED):
            raise ValueError(f"{slot}={text!r} bundles concepts or addresses the patient")

    if not r.concept:
        raise ValueError("concept is required")
    if len(r.concept.split()) > 2:
        raise ValueError(f"concept={r.concept!r} is over two words")
    if r.character and len(r.character.split()) > 1:
        raise ValueError(f"character={r.character!r} must be one word")
    if len(r.site.split()) > 2:
        raise ValueError(f"site={r.site!r} is over two words")


def band_distance(a: str, b: str, order: list[str]) -> float | None:
    """Ordinal distance in [0, 1], or None when either side says nothing.

    None is a no-op rather than a mismatch: most NHS pages state no duration,
    and a silent corpus row must not be punished by a patient who spoke.
    """
    scale = order[:-1]  # drop `unspecified`
    if a not in scale or b not in scale:
        return None
    return abs(scale.index(a) - scale.index(b)) / (len(scale) - 1)


def facet_multiplier(corpus: Record, patient: Record) -> float:
    """How much of a matched symptom's weight survives its facet disagreement."""
    seen = [d for d in (band_distance(corpus.onset, patient.onset, ONSETS),
                        band_distance(corpus.duration, patient.duration, DURATIONS))
            if d is not None]
    if not seen:
        return 1.0
    return max(FACET_FLOOR, 1.0 - sum(seen) / len(seen))


# Handed to the flash model by both normalisation passes and by the query path,
# so corpus and patient text come back under one contract.
GEMINI_SCHEMA = {
    "type": "object",
    "properties": {
        "records": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "concept": {"type": "string"},
                    "character": {"type": "string"},
                    "site": {"type": "string"},
                    "onset": {"type": "string", "enum": ONSETS},
                    "duration": {"type": "string", "enum": DURATIONS},
                    "duration_text": {"type": "string"},
                    "severity": {"type": "string", "enum": SEVERITIES},
                    "progression": {"type": "string", "enum": PROGRESSIONS},
                    "polarity": {"type": "string", "enum": POLARITIES},
                },
                "required": ["concept", "polarity"],
            },
        }
    },
    "required": ["records"],
}
