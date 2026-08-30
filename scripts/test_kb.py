#!/usr/bin/env python3
"""Self-check for the KB schema and loader. Run: uv run python scripts/test_kb.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "engine"))

import pydantic  # noqa: E402

from dx_engine.kb import Condition, Feature, Source, Variable, load  # noqa: E402


def rejects(fn, why: str) -> None:
    try:
        fn()
    except (pydantic.ValidationError, ValueError):
        return
    raise AssertionError(f"should have been rejected: {why}")


def var(**kw):
    base = dict(name="v", prompt="Is it there?", modality="history", values=["a", "b", "unknown"])
    return lambda: Variable(**(base | kw))


# question-precision lints
rejects(var(prompt="Is there fever and cough?"), "compound stem")
rejects(var(prompt="Is there fever or cough?"), "compound stem")
rejects(var(prompt="Fever present"), "not a question")
rejects(var(prompt="Is there " + "very " * 15 + "much fever?"), "over 15 words")
rejects(var(values=["a", "b"]), "no unknown value")
rejects(var(values=["a", "a", "unknown"]), "duplicate values")
rejects(var(values=["unknown"]), "single value")
rejects(var(modality="investigation"), "investigation is not a legal modality")
assert Variable(**dict(name="v", prompt="Is it there?", modality="history",
                       values=["a", "b", "unknown"])).cost == 0

# licensing guard
rejects(lambda: Source(type="guideline", title="t", url="https://cks.nice.org.uk/x",
                       licence="l"), "CKS content is not licensed for reuse")
rejects(lambda: Source(type="guideline", title="t"), "non-estimate without url/licence")
assert Source(type="estimate", title="t").url is None

# features
rejects(lambda: Feature(expect=[], source="s"), "empty expect")
rejects(lambda: Feature(expect=["unknown"], source="s"), "unknown as an expectation")
assert Feature(expect=["a"], source="s").weight == 1.0, "weight must default to 1"

# conditions
c = Condition(slug="s", name="n", parents=["p1", "p2"], urgency="routine")
assert c.primary_parent == "p1", "first parent is the primary one"
assert Condition(slug="s", name="n", urgency="routine").prior is None

# the real KB loads and is deterministic
kb = load(Path(__file__).resolve().parents[1] / "data")
assert load(Path(__file__).resolve().parents[1] / "data").version_hash == kb.version_hash
assert kb.conditions["pulmonary-embolism"].primary_parent == "vascular"
assert len(kb.conditions["pulmonary-embolism"].parents) == 2, "PE must be multi-parent"

print(f"all checks passed — kb {kb.version_hash}, {len(kb.conditions)} conditions")
