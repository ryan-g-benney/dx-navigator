# Phase 0 revision — Match scoring and leaf adjacency, without likelihoods

**Date:** 2026-08-30
**Status:** proposed. Supersedes the inference half of
`phase-0-architecture-position.md`; the rule-layer half is unaffected.

The engine ranks by **signed feature match**, not probability. Likelihoods are
deferred, not designed out — §5 shows why introducing them later is a data change
with no engine change.

---

## 1. Why this is a good simplification, not just a cheap one

Three reasons beyond "it's less work".

**It matches what the tool is for.** The brief's §2 says the value is surfacing
the condition they hadn't thought of. A GP looking at acute cough already knows
it is probably a chest infection — the ranking's top slot tells them nothing. The
product is the second through fifth rows, and the reason a row is there. That is
an adjacency problem, and adjacency does not need probability.

**It removes the failure mode I flagged.** The architecture position warned that
naive Bayes over ~30 conditions would be systematically overconfident, posteriors
piling above 0.9, needing a damping constant fitted post-hoc. A match score makes
no confidence claim at all, so there is nothing to be overconfident with and
nothing to calibrate. The §5 metric I said was unmeasurable at our vignette count
simply stops applying.

**It tests the expensive assumption cheaply.** Nobody knows whether graded
likelihoods actually move top-3 accuracy over flat matching *for this knowledge
base*. Build the flat version, run the eval, and the number decides whether the
graded version is worth four more weeks of authoring. That is the experiment from
the acquisition plan, now much cheaper to run.

---

## 2. The scoring rule

For condition `C` and answer set `A`:

```
score(C, A) = Σ  +w(C,v)   if A[v] ∈ C.expected[v]        # match
                 −w(C,v)   if A[v] ∉ C.expected[v]        # mismatch
                  0        if A[v] is unknown
                  0        if C does not state v           # sparse: silent

  over every variable v that appears in BOTH A and C.expected

normalised = score / Σ |w(C,v)|          → lands in [−1, +1]
evidence   = count of terms actually summed
```

`w(C,v)` is **1 for every cell today.** It is the field that becomes the graded
ordinal later. See §5.

**Ranking:** sort by `normalised` descending, tie-break by `evidence` descending.

**Three properties that fall straight out, and they are the ones the brief asks
for:**

- **`unknown` is a genuine no-op.** It contributes zero, not a small penalty.
  A patient answering `unknown` throughout scores 0 everywhere and lands in
  "insufficient evidence" — never on a confident top rank.
- **Undo is free.** Score is a pure function of the answer set. Addition
  commutes, so dropping an answer and recomputing is exact. §3's recoverability
  requirement is satisfied by the arithmetic, not by machinery.
- **Order-invariance is trivially true** and property-testable on day one.

### 2.1 Two decisions that are easy to get wrong

**Mismatch must cost something.** If a mismatch scored 0 instead of −1, a
condition would be rewarded for merely *having* a long feature list — more
chances to match, no risk. Scoring −1 also makes "no fever" actively argue
against pneumonia, which is clinically what a GP means.

**Normalisation needs an evidence floor.** Dividing by the number of contributing
terms fixes verbose conditions outranking concise ones, but introduces the
opposite bug: a condition stating two features, both matched, scores a perfect
1.0 and beats one where nine of ten matched at 0.9. So:

> A condition with `evidence < 3` is displayed with an **insufficient evidence**
> marker and is not eligible for rank 1.

One rule, kills the failure, and it is honest on the screen rather than hidden in
the maths.

---

## 3. Adjacency — the part that is actually the product

Two kinds. They answer different clinical questions and both are worth having.

### 3.1 Hierarchical adjacency — "what else is in this family?"

Straight off the DAG from the SNOMED subposet: siblings under the shared parent,
ranked by least-common-ancestor depth. Two leaves under the same immediate parent
are nearer than two sharing only a top-level category.

Answers the completeness question. *We have landed on community-acquired
pneumonia — what else sits under lower respiratory tract infection that we have
not excluded?* Cheap, and it uses the hierarchy we are building anyway.

### 3.2 Flip adjacency — "what is this ranking hinging on?"

The better one, and I think it is the feature that makes the tool worth opening.

> **Condition B is 1-flip adjacent to top-ranked A** if changing exactly one
> answer would make B outrank A.

Computable by brute force: for each answered variable, for each alternative value
it could have taken, rescore and see who wins. With ~30 conditions, ~8 answered
variables and ~4 values each, that is roughly 1,000 score evaluations — a
millisecond, no cleverness required.

What it puts on screen:

> *"This ranking hinges on question 3. If the crackles were bilateral rather than
> focal, heart failure would rank first."*

That is more useful to a clinician than `0.62`, and it is honest in a way a
probability is not: it names the specific answer the conclusion depends on,
which is exactly the answer a GP might have recorded loosely under time pressure.
It is also the natural companion to the undo requirement — it tells you *which*
answer is worth revisiting.

Flip adjacency needs no probability. It works today.

### 3.3 Divergence between the two

Where a condition is flip-adjacent but hierarchically distant, that is the
interesting case and it should be surfaced prominently — it is a near-miss from a
completely different part of the DAG. *Pulmonary embolism is one answer away and
it is not in the infective family at all.* That is precisely the "condition they
hadn't thought of" the brief exists to surface.

---

## 4. Question selection without information gain

The one place the simplification genuinely costs us. Expected information gain
needs a distribution. The substitute:

> **Split the leaders.** Among unanswered variables, pick the one whose values
> most evenly partition the current top-k candidates.

For each candidate variable, group the current top-k by the value each condition
expects, then score the variable by how evenly it splits them (Gini over the
group sizes is fine, and it is four lines). Prefer variables that split the
leaders; ignore ones where every leader expects the same value, since they cannot
change the order.

This is the same calculation as expected information gain with all weights set to
1 — the same consistency as §5 below. The cost model layers on unchanged:
history is free, examination costs more, and `investigation` remains an
illegal question modality per the source investigation.

---

## 5. The migration path — why likelihoods are a data change, not an engine change

This is the load-bearing claim, and it is worth stating precisely.

Naive Bayes in log-odds form is:

```
log posterior odds = log prior odds + Σ log(LR_v)
```

Set every `LR` to a constant `k` for a match and `1/k` for a mismatch:

```
Σ log(LR_v) = (matches − mismatches) × log k
```

**Which is the signed match count, scaled by a constant.** The scoring rule in §2
is not a different algorithm from the one in the architecture position — it is
that algorithm with the 7-point ordinal collapsed to `{for, against}` and the
prior held flat.

So the migration is:

| | Today | Later |
|---|---|---|
| `w(C,v)` | always 1 | `log` of the 7-point ordinal: 1/10, 1/4, 1/2, 1, 2, 4, 10 |
| Prior | flat | UK primary-care base rate |
| Output | signed match score | posterior |
| **Engine code** | | **unchanged** |

**Store the `weight` field in the schema now**, defaulted to 1. Store the `prior`
field now, defaulted to uniform. Then introducing likelihoods is populating two
columns, and §13 of the brief — *if adding a condition requires touching
`packages/engine/`, the engine is wrong* — is satisfied for the largest change we
already know is coming.

This costs two nullable fields today. It is the cheapest insurance in the project.

---

## 6. What we lose, honestly

**All evidence weighs the same.** A pathognomonic finding counts exactly as much
as a common one. Thunderclap onset scores the same as "has a headache". That is
clinically wrong and it is the real cost of this simplification.

It is **partly absorbed by the rule layer that already exists.** Thunderclap
onset should be a red-flag rule, not a piece of graded evidence — it mandates an
action regardless of what the ranking says. The findings most damaged by flat
weighting are largely the ones that belong in the rule layer anyway. Not a
complete answer, but it means the loss lands mostly on the findings where it
matters least.

**No confidence claim.** Correctly, for now. The report says "these five, ranked,
here is the evidence for each" and does not say how sure it is. That is more
honest than an uncalibrated number and it removes the §5 calibration metric,
which I argued was unmeasurable at our vignette count anyway.

**Eval targets may not be met.** Top-3 ≥ 0.85 may or may not be reachable on flat
weights. That is the experiment, and finding out is the point.

---

## 7. What is unaffected

**The entire rule layer.** §1 of the architecture position required that rules
never write to the belief state — they emit actions only. Deleting the
probabilistic half entirely therefore disturbs nothing: red flags, referral
criteria, escalation and safety-netting all still fire off the raw answer set.

That is worth noting as evidence the layering was right. An architecture whose
inference half can be swapped out without touching the safety half is the one you
want in this domain.

Also unaffected: the DAG and SNOMED work, all licensing conclusions, the
provenance schema, the validator lints, the audit log, the API surface, and every
accessibility and safety requirement.

---

## 8. What this does to the schedule

Authoring collapses. Instead of 300 graded ordinal judgements, it is ~300
**ternary** ones — *typical for this condition / argues against / not relevant* —
which a GP can work through several times faster and a second clinician can
review by eye.

| | Graded | Flat |
|---|---|---|
| Authoring complaint 1 | ~2 days GP time + literature track | **~half a day, no literature track** |
| Complaint 1 end to end | ~3 weeks | **~1 week** |
| All three complaints | ~6–7 weeks | **~2–3 weeks** |

The literature track can be dropped entirely for now, because flat weights cannot
express what a published likelihood ratio would tell us. That removes the
spectrum-bias adjudication that was the dominant cost — though it comes straight
back when weights are introduced, so the sourcing work in the acquisition plan is
deferred, not cancelled.

---

## 9. Open question this raises

The evidence floor in §2.1 is set at `evidence < 3`. That number is a guess. It
should be picked against the eval once vignettes exist, not chosen now — flagging
it so it does not silently become a magic constant nobody revisits.

---

## 10. Next step

If this is approved, Phase 0 is complete and the next step is the spec, per §10.1
of the brief — still not code. ADRs to write: this decision and its migration
path, plus the rejected alternative of building graded likelihoods first.
