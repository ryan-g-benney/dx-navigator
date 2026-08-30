# Phase 0 — Architecture Position

**Status:** proposal, awaiting sign-off. No code written.
**Date:** 2026-08-30

> **Superseded in part, 2026-08-30.** The inference half of this document
> (naive Bayes, likelihood authoring, calibration) is deferred — see
> `phase-0-simplified-engine.md`, which replaces it with signed feature
> matching and shows why likelihoods can be reintroduced as a data change.
> The rule-layer argument in §1, the hierarchy analysis in §3, and every
> criticism in §4 still stand unchanged.

> **No clinical assertion in this document is source-verified.** Examples are
> reused from the brief for illustration. Nothing here should be carried into
> `data/` without checking it against NICE CKS first, per
> `agent-skills:source-driven-development`.

---

## 1. Recommendation

Adopt **(d), the hybrid** — but with a constraint the brief does not state, and
which I think is the difference between (d) working and (d) becoming MYCIN with
extra steps:

**The rule layer is not an inference engine. It never writes to the belief state.**

Concretely, three properties:

1. **Rules do not chain.** No rule consumes a fact derived by another rule. Every
   rule is a pure predicate over `(answers, demographics)` and nothing else.
2. **Rules emit actions, not evidence.** A rule's return type is
   `Recommendation | MustAsk | Escalation | SafetyNet`. There is no field on that
   type that can touch a probability. Make this a type-level guarantee, not a
   convention — it is the single load-bearing invariant in the design.
3. **Rules and beliefs are rendered side by side and never merged.** There is no
   resolution step, so there is nothing for a resolution step to get wrong.

This kills the two objections the brief raises against (a) outright. Conflict
resolution stops being a research problem because rules never compete for control
of a variable — they each independently emit an action, and actions union. Rule
rot is bounded because a rule with no chaining is a unit-testable function with a
fixed signature.

It also makes the recoverability requirement (§3) nearly free, which is the
argument I would make against (a) and (c) if you needed one. Belief is a pure
function of the answer *multiset*; a rule is a pure function of the same. Undo is
"drop the answer, recompute" — no truth maintenance, no retraction of derived
facts, no unwinding. Hard tree traversal (c) cannot do this at all, and a chaining
rule engine (a) can only do it by rebuilding the whole derivation.

### 1.1 Does the rule layer earn its complexity?

Yes. Your candidate answer is right, but the sharper version of it is:

**Rules and likelihoods optimise different loss functions.** A posterior answers
"what is most likely". A referral rule answers "what does it cost to be wrong".
Your own example — haemoptysis + age ≥ 40 + smoker — will sit somewhere down the
ranking in any honest posterior, because it is genuinely not the most likely
explanation. It still mandates a 2-week-wait referral. That is an asymmetric
utility, and a likelihood table has no place to put one.

The obvious counter is "so use a probability threshold — refer if P(cancer) > x".
That fails on inspection: x has to be tuned per condition, per referral pathway,
and the resulting constant is unauditable and unattributable to a guideline.
It *is* the rule, with worse provenance and no NICE URL to hang on it. So the
claim survives the test you asked me to run.

**But the argument only works for actions.** The moment a rule says
`IF haemoptysis THEN P(cancer) = 0.9`, your objection lands squarely and the rule
layer becomes a probability table with worse maths. That is exactly why property
(2) above is a type constraint. The line between "rule earns its keep" and "rule
is bad statistics" is precisely the line between emitting an action and writing a
belief.

### 1.2 Where a likelihood beats a rule

Everything graded and combinable, which is most of the knowledge base. Cough
character, fever, onset speed, pleuritic quality — each nudges several conditions
by different amounts, and the nudges must compose. Expressing that as rules
produces combinatorial explosion, which is (a)'s real failure mode.

---

## 2. What the engine actually is — stated plainly

It is **naive Bayes over a curated leaf set, with engineered non-redundant
variables**. I want that written down without decoration, because the brief's
framing ("probabilistic belief as the engine") makes it sound like more than it
is, and because most of the correctness does not live in the inference at all.

The brief warns that naive independence is wrong. It is. But the fix the brief
*already specifies* in §4 — collapsing correlated findings into single categorical
variables — is the correct fix and, at this scale, a sufficient one. It handles
the dominant correlation structure by construction. A full Bayesian network with
authored CPTs is not authorable by a clinician and we have no data to learn
structure from, so it is not on the table.

**The consequence, which has a staffing implication:** the hard part of this
project is variable design and clinical authoring, not Python. The schema is doing
more work than the engine. If the variables are right, naive Bayes is adequate; if
the variables are wrong, no inference method saves it.

**Expected problem:** naive Bayes over ~30 conditions will be systematically
overconfident — posteriors will pile up above 0.9. That is a calibration failure,
not a ranking failure, and the two should not be confused. Mitigation is a single
global damping exponent on the log-likelihoods, fit once against the vignette set,
plus displaying an ordinal band (`likely / possible / consider`) alongside the
number rather than instead of it. Hiding the number breaks "explainable at every
step"; showing only the number invites false precision. Show both, and say in the
README that it is a curated-prior model output, not an observed frequency.

Per your own rule in §13, the damping constant gets fitted *after* the baseline
eval, not before.

---

## 3. Is the hierarchy load-bearing?

Honest answer: **not for the belief update. Yes for the question objective and for
authoring.** You asked me to say so if it was cosmetic, and it is partly cosmetic,
so here is the split:

- **Not load-bearing for inference.** In naive Bayes over leaves, the posterior
  does not care what the parents are. The DAG contributes nothing to the maths.
- **Load-bearing for question selection.** This is the real one. Expected
  information gain computed over leaves alone will happily choose a question that
  finely splits two rare leaves. Computing gain over the *category partition*
  first — "is this infective, cardiac, embolic, or malignant?" — biases toward big
  early splits and produces the shallow, GP-narrative-shaped sequence you want.
  **This is what makes median ≤ 6 reachable.** Without it, the greedy optimiser
  wanders.
- **Load-bearing for authoring.** A child inherits its parent's feature
  likelihoods unless it overrides them. This is a large reduction in clinician
  authoring burden and directly serves "extensible by clinicians, not engineers".
- **Cosmetic but non-negotiable:** breadcrumb, pruning display, "what did you
  discard on my behalf".

**Data-model consequence:** categories carry priors and likelihoods (for
inheritance and for the category-level gain calculation), but the belief vector is
over **leaves only**. Do not maintain belief at interior nodes; it is a second
source of truth and it will drift.

---

## 4. Where I think the brief is wrong

Six things, in descending order of how much they matter.

### 4.1 "Median ≤ 6 questions" conflates two budgets

Discriminating questions and mandatory red-flag questions are different things
with different justifications, and blending them into one median hides the failure
mode you most need to see.

Chest pain is the case in point. ACS, PE, dissection, pneumothorax and
oesophageal rupture each carry their own exclusion criteria. Asking about all of
them honestly exceeds six questions on its own, before any discrimination has
happened. A blended median forces one of two bad outcomes: the optimiser skips
red flags to hit the target, or the target is quietly missed and the metric
becomes noise.

**Proposal:** report `median_discriminating_questions` and
`median_mandatory_questions` separately. Gate on the first (≤ 6). Do not gate the
second at all — it is whatever clinical policy says it is. If chest pain lands at
5 discriminating + 4 mandatory = 9, that is correct behaviour, not a regression.

### 4.2 Cost-awareness should be a hard modality boundary, not a soft penalty

§3 frames investigation cost as a term in the objective. That is weaker than it
needs to be. In a 10-minute consultation there is no d-dimer. There is no CT. The
system should be structurally incapable of asking for one.

**Proposal:** every question carries `modality: history | examination |
point_of_care`. `investigation` is not a modality a question may have — an
investigation is an *output* (a recommendation the report makes), never an
interrogation step. Soft cost still lives inside the allowed modalities to
separate free history from a chest examination. This removes an entire class of
"it asked for a CT as question two" failure by construction rather than by tuning
a weight and hoping.

### 4.3 "Calibration error ≤ 0.05" is a metric that will produce a fake green light

You cannot measure calibration to 0.05 with a few dozen curated vignettes. The
confidence interval on that estimate is wider than the threshold. It will report a
number, CI will go green, and the number will mean nothing.

**Proposal:** either resource the vignette set to a few hundred (expensive, and
they are synthetic anyway, so it measures agreement with our own priors rather
than with reality), or replace the metric with ranking metrics plus an explicit
qualitative overconfidence check ("what fraction of runs end above 0.9, and is
that plausible?"). I recommend the latter and would rather say "not measurable at
this n" in the README than ship a green tick that is not real.

### 4.4 Non-discriminating questions: not at all, with one exception

You ask: off the critical path, or not at all? **Not at all.** The GP has already
asked about duration; they are in the room. A tool that re-asks is precisely the
patronising, time-wasting behaviour that gets it closed for good.

The exception is variables that carry no information about the *diagnosis* but do
determine *urgency or safety-netting text* — severity often does this. Those are
not informationally worthless; they have zero mutual information with respect to
the condition and non-zero with respect to the action. The principled fix is to
compute information gain over the **output**, not the diagnosis. That is a
sophistication your §13 says to defer until the eval proves the simple version
insufficient, and I agree.

**Lazy version, which I recommend for now:** mark these `role: disposition`. Never
selectable by the optimiser. Collected on the report screen, only when a fired
rule actually needs one, and pre-fillable. Note the fuller version as deferred.

### 4.5 Move a skeleton eval to step 3.5

The build order puts the eval harness at step 8, after the engine and the red-flag
layer. Running a handful of vignettes against the knowledge base as soon as it
loads — before any inference exists — catches knowledge-base errors when they are
cheapest to fix. It is a small amount of work and it front-loads the thing most
likely to be wrong.

### 4.6 The engine signature

`step(state, answer) -> state` should be `step(kb, state, answer) -> state`. The
knowledge base is an input to the pure function, not part of session state — it is
versioned separately, and it must not be serialised into every session row. Small,
but it is the sort of thing that is painful to change once written.

---

## 5. Answers to the rest of §1.2

### 5.1 Operational definition of a precise question, and the lint

| Your criterion | How it is enforced |
|---|---|
| One concept | **Schema, not lint.** A question *is* a variable's prompt — one question, one variable, structurally. Lint additionally rejects `and` / `or` / a comma in the stem outside a parenthetical. |
| Answerable now, in the room | `modality` field; `investigation` is not a legal value (§4.2). |
| MECE answers | Lint: ≥ 2 values; exactly one `unknown`; `unknown` excluded from the discriminating set; no value's label is a substring-superset of another's; **every value referenced by at least one condition's likelihood table** — an unreferenced value is dead weight and is an error, not a warning. |
| Two GPs phrase it the same | **Not machine-checkable.** Proxies only: stem ≤ 15 words, ends in `?`, banned hedging words (`perhaps`, `any sort of`, `at all`), no second-person qualifiers. Plus a required `phrasing_reviewed_by` field. I want this limitation stated in the validator output rather than implied by a passing build. |

One lint you did not ask for, which I think matters more than most of the above:
**a discrimination floor.** Any question whose maximum achievable information gain
across all reachable belief states is below ε can never move the ranking. It was
authored out of clinical habit. Flag it — it is knowledge-base bloat that costs
consultation time and buys nothing.

### 5.2 Who authors the likelihoods, and how

**Never ask a clinician for a probability.** Ask for a 7-point ordinal on "how
much does this finding make you think of this condition":

`strongly against | against | slightly against | neutral | slightly for | for | strongly for`

mapped to fixed likelihood ratios (something like 1/10, 1/4, 1/2, 1, 2, 4, 10).
Clinicians reason natively in likelihood ratios — "that really makes me think PE"
*is* a likelihood ratio — and reason badly in absolute probability. The mapping
constants are a single tunable table fitted once against the eval set, not
per-cell numbers. It also makes the knowledge base reviewable by a second
clinician, which a spreadsheet of decimals is not.

Base prevalence is the one number they must supply directly, and it is elicited as
a **frequency**, not a probability: "how many of these do you see per 1000
consultations *for this presenting complaint*, in UK primary care". Frequencies
are elicited far more reliably than probabilities. Provenance forces a NICE CKS
URL or an explicit `estimate` marker.

**Sparsity is mandatory, and it is a schema decision, not an optimisation.** Dense
authoring is ~30 conditions × ~20 variables × ~3 values ≈ 1800 cells. Nobody will
author that, and nobody will review it. A condition states likelihoods only for
variables it actually shifts; anything unstated has likelihood ratio 1. That takes
it to roughly 8–12 stated variables per condition — a few hundred ordinal
judgements, which is a realistic ask.

### 5.3 Smallest non-toy knowledge base

3 complaints, 10–12 leaf conditions each (~30–36 total), ~45–60 variables, ~25
rules.

Below ten leaves per complaint a GP spots the missing condition immediately and
never opens it again — that is the toy threshold, and it is a trust threshold, not
a maths one. Above fifteen, the authoring and source-verification cost outruns
what we can honestly check against NICE CKS in this project.

### 5.4 Complaint selection

Agree with two of your three; one comment and one alternative.

- **Acute cough / breathlessness — yes, build first.** Best discrimination test,
  as you say.
- **Chest pain — yes, build second.** For the reason in §4.1: it honestly breaks
  the six-question budget, which is exactly why it belongs in the set. It also
  overlaps heavily with complaint 1 (PE, ACS appear in both), and that overlap is
  a feature — it exercises the multi-parent DAG claim and forces condition reuse
  across complaints rather than letting us copy-paste.
- **Headache — keep, build third, with an expectation set.** It tests the red-flag
  machinery well (thunderclap, GCA, raised ICP, meningitis against a benign
  majority). But it is the *weakest* discrimination test in the set: tension vs
  migraine vs medication-overuse is genuinely hard on history alone. The eval will
  look bad for honest reasons, and it will be the complaint where "insufficient
  information" fires most. That is the correct behaviour and it will read as a
  failure unless we say so up front.
- **Alternative I considered and rejected: fatigue / "tired all the time".**
  Highest-frequency vague presentation in UK general practice, and where GPs most
  want help. I did not swap it in because it is largely investigation-driven,
  which collides with the modality boundary in §4.2, and because headache's
  catastrophic tail is the better test of the safety machinery — and the safety
  machinery is the part that must not be wrong. Flagging it as the obvious
  complaint 4.

### 5.5 Stopping, and "insufficient information"

A first-class terminal state, not a fallback. Stop and declare insufficient when,
after the question budget, no leaf clears threshold **and** the top candidates are
not clinically equivalent in disposition. "I cannot separate these three; all three
are routine; here is the safety-netting" is a genuinely useful output and is much
safer than a confident number one. This is the mechanism by which the system
degrades toward humility rather than nonsense, per §3.

---

## 6. Assumptions I am proceeding on

1. Clinical content is authored by me from NICE CKS with citation, then reviewed —
   not authored by a practising GP from scratch. This is the honest default; §7
   asks you to correct it.
2. No real patient data, ever, in this build. Vignettes are synthetic. No
   identifiers by design (§9).
3. Single-language, UK-only, adult-only for the seed. Paediatric presentation is a
   different knowledge base, not a modifier.
4. `unknown` is a genuine no-op — likelihood ratio 1 across all conditions, never
   a weak signal. A patient answering `unknown` to everything must land in
   "insufficient information", never on a top-ranked condition.
5. The question sequence is *not* order-invariant (greedy selection is
   path-dependent); the *belief* is. Two separate property tests, easily conflated
   into one wrong one.
6. Emergency red-flag recall at 1.00 is a gate on the seed vignette set, and I will
   say explicitly in the README that this is not a claim about real-world recall.

---

## 7. Open questions — blocking

1. **Who authors the clinical content?** Is a GP available to author or review the
   knowledge base, or is assumption (6.1) correct? This changes the authoring
   format design and, more importantly, changes what we can honestly claim.
2. **Chest pain scope.** Accept that it exceeds six questions (my recommendation,
   per §4.1), or narrow it to non-traumatic adult chest pain in a patient who is
   stable in front of you?
3. **Calibration metric.** Replace it as I propose in §4.3, or resource a
   several-hundred-vignette set?
4. **Regulatory.** Confirm this will not touch a real patient before you have the
   UK MDR question answered by a regulatory specialist. I am flagging, not
   classifying — as instructed.
5. **Audience for the demo.** Going in front of GPs for feedback, or an engineering
   demonstration? It decides how much of the budget goes to the frontend versus
   the knowledge base, and they compete.
6. **Complaint 3.** Keep headache (my recommendation) or swap for fatigue?

---

## 8. Rejected alternatives

| Option | Why rejected |
|---|---|
| **(a) Pure rule-based expert system** | Combinatorial explosion on graded evidence, which is most of the knowledge base. Certainty-factor algebra is not probabilistically coherent — your objection stands and I have no defence for it. Chaining makes the recoverability requirement (§3) expensive: undo needs truth maintenance. Survives only as the non-chaining action layer described in §1. |
| **(b) Pure probabilistic** | Cannot express categorical clinical policy. Burying a 2-week-wait criterion in a posterior is both wrong (it optimises the wrong loss function) and unsafe (it can be outvoted by evidence). Also strictly less persuasive to a clinician than a named rule with a NICE URL on it. |
| **(c) Hard tree traversal** | Fails three of your §3 requirements outright: not recoverable (one mis-answer is unrecoverable), cannot represent a condition under two parents, cannot express "probably A but possibly B". Brittle exactly when a GP most needs help. No defence. |
| **Full Bayesian network with authored CPTs** | Not authorable by a clinician; no data to learn structure from. Violates "no sophisticated version until the simple one is proven insufficient". Revisit only if eval shows the collapsed-variable approach failing on a specific correlated cluster. |
| **LLM-in-the-loop for ranking or question choice** | Not traceable, not reproducible from an answer log plus a knowledge-base hash, not auditable against a guideline. Fails §3 outright. Possibly defensible later for free-text intake mapping onto the controlled vocabulary — nowhere near the inference path. |

---

## 9. If you sign this off

Next step is §10.1 — the spec, via `agent-skills:spec-driven-development` — not
code. ADRs to be written for: hybrid architecture with the no-chaining constraint
(§1), naive Bayes and the variable-design consequence (§2), hierarchy load-bearing
only for objective and authoring (§3), split question budgets (§4.1), modality
boundary (§4.2), ordinal likelihood authoring (§5.2), and each rejected option in
§8.
