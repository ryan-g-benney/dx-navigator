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

# complaint pools are a cover, not a partition
pools = {c: [n for n, comp in kb.complaints.items() if c in comp.pool] for c in kb.conditions}
assert len(pools["pulmonary-embolism"]) == 2, "PE must be reachable from two complaints"
assert len(kb.complaints) == 3
for name, comp in kb.complaints.items():
    assert len(comp.pool) >= 9, f"{name} pool too small to be non-toy"
# every emergency condition carries at least one red flag
for slug, c in kb.conditions.items():
    if c.urgency.value == "emergency":
        assert c.red_flag_features, f"{slug} is an emergency with no red flag"

# --- engine behaviour ---
from dx_engine import session as S  # noqa: E402
from dx_engine.score import rank  # noqa: E402

# unknown is a genuine no-op, not a weak signal
base = {"cough_character": "productive_purulent", "fever_history": "present"}
assert rank(kb, "acute-cough", base) == rank(kb, "acute-cough", base | {"orthopnoea": "unknown"})

# belief is order-invariant even though the question sequence is not
a = S.start("acute-cough")
for k, v in base.items():
    a = S.step(kb, a, k, v)
b = S.start("acute-cough")
for k, v in reversed(list(base.items())):
    b = S.step(kb, b, k, v)
assert [r.slug for r in S.view(kb, a).ranked] == [r.slug for r in S.view(kb, b).ranked]

# undo is exact: it restores the earlier state, nothing to unwind
assert S.undo(S.step(kb, a, "orthopnoea", "present")).answers == a.answers

rejects(lambda: S.step(kb, a, "orthopnoea", "sideways"), "illegal value for a variable")
rejects(lambda: S.step(kb, a, "no_such_variable", "present"), "unknown variable")

# an escalation reached before the differential separates must be provisional,
# and must list every emergency it has not excluded
diss = {"chest_pain_character": "tearing", "chest_pain_radiation": "between_shoulder_blades",
        "pain_onset_abruptness": "instant_maximal", "autonomic_symptoms": "present",
        "chest_pain_duration": "constant", "chest_pain_relief": "nothing",
        "reproducible_on_palpation": "absent"}
st = S.start("chest-pain")
while (v := S.view(kb, st)).stop is S.Stop.ONGOING:
    st = S.step(kb, st, v.question, diss.get(v.question, "unknown"))
v = S.view(kb, st)
assert v.stop is S.Stop.EMERGENCY
assert v.provisional, "early escalation must not be presented as an answer"
assert "aortic-dissection" in v.emergency_outstanding

# unknown never satisfies a rule clause, so it cannot trigger an escalation.
# That is deliberate -- a no-op must not be a weak yes -- and the outstanding
# emergency list is what stops the omission being silent.
thin = dict(diss, chest_pain_duration="unknown")
st2 = S.start("chest-pain")
while (v2 := S.view(kb, st2)).stop is S.Stop.ONGOING:
    st2 = S.step(kb, st2, v2.question, thin.get(v2.question, "unknown"))
v2 = S.view(kb, st2)
assert v2.stop is not S.Stop.EMERGENCY
assert "aortic-dissection" in v2.emergency_outstanding

# answering unknown to everything must never produce a confident leader
st = S.start("acute-cough")
while (v := S.view(kb, st)).stop is S.Stop.ONGOING:
    st = S.step(kb, st, v.question, "unknown")
assert S.view(kb, st).stop is S.Stop.INSUFFICIENT

print(f"all checks passed — kb {kb.version_hash}, {len(kb.conditions)} conditions")
