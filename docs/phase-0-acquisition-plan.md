# Phase 0 addendum — Data acquisition plan

**Date:** 2026-08-30
**Answers:** which source to extract from, how long it takes, and how the
order-theoretic structure should actually be built.

**Revised 2026-08-30** after inspecting the NHS content API payloads directly.
Sections 9–12 are new: the NHS verdict is corrected, model delegation is costed,
and the schedule question is answered with scope options.

---

## 1. The short answer

**There is no single site worth crawling, and crawling is not the long pole.**

The work splits into three acquisition tracks with wildly different costs. Only
one of them is a crawl, and it is the cheapest of the three by an order of
magnitude:

| Track | What it gives | Method | Cost |
|---|---|---|---|
| **A. Skeleton** | Condition list, codes, the hierarchy itself | Download SNOMED CT UK from TRUD | ~2 days, mostly waiting for an account |
| **B. Rules** | Red flags, referral criteria, safety-netting | ~15 named NICE guidelines, fetched individually | ~1 week |
| **C. Likelihoods** | The numbers the engine actually runs on | Targeted literature + clinician elicitation | **~4–6 weeks, and it gates everything** |
| **D. Safety-netting** | Patient-facing "when to seek help" text | NHS website content API | ~1 day (added — see §9) |

If you take one thing from this document: **the extraction you are asking about
is Track A, and it is two days.** The project's schedule is set by Track C, which
cannot be crawled from anywhere because the data does not exist in structured
form on any website.

---

## 2. Why bulk condition→symptom extraction does not work — tested, not asserted

The obvious plan is to find a site with condition→symptom pairs and pull the lot.
I checked whether that is viable before recommending against it.

**Wikidata** is the only genuinely bulk-queryable source: property `P780`
(`symptoms and signs`), CC0 licensed, open SPARQL endpoint, no scraping needed.
It is the strongest possible case for the bulk approach. Query results:

Best-annotated diseases by symptom count:

```
NGLY1-deficiency          73 symptoms
Creutzfeldt-Jakob disease 54
tetrodotoxin poisoning    25
Barth syndrome            23
Behçet's disease          22
amnesic shellfish poisoning 20
```

Coverage for the conditions we actually need:

```
pneumonia                                7 symptoms
myocardial infarction                    5
migraine                                 5
heart failure                            5
asthma                                   4
chronic obstructive pulmonary disease    3
pulmonary embolism                       2
tension headache                         1
```

**Coverage is inversely proportional to primary-care relevance.** The annotation
effort has gone where the enthusiasts are — rare, genetic and exotic disease.
Pulmonary embolism, a condition this system exists to catch, has two symptoms
recorded. Tension headache has one.

And even the best row is unusable. Seven symptoms for pneumonia gives us:

- no **strength** — is fever weak or strong evidence?
- no **direction** — nothing records that a finding argues *against* a condition,
  and negative findings do much of the discriminating work
- no **base rate**, and certainly not a UK primary-care one
- no **provenance** we could put in front of a clinician

So the bulk sources fail on both coverage and on shape. This is not a case for
being careful with a noisy source; it is a case for not using it at all. The same
argument disposes of the other candidates: HPO and Orphanet are rare-disease
ontologies, UMLS co-occurrence and SemMedDB give MEDLINE term co-occurrence
rather than clinical association strength, and none carry a primary-care prior.

**Conclusion: there is no shortcut around authoring. Plan for authoring.**

---

## 3. Track A — the skeleton, and the order theory

This is the part your question is really about, and your instinct is right, with
one correction.

### 3.1 The poset already exists — borrow it, do not derive it

SNOMED CT is a description-logic ontology. Its `116680003 |Is a|` relationship
gives a **poly-hierarchy** over roughly 350,000 concepts: acyclic, multi-parent,
and classified by a DL reasoner. That is a poset, and its Hasse diagram is
precisely the DAG the brief asks for in §4.

We do not need to construct a hierarchy. We need to **select a subposet**:

1. Load `sct2_Relationship_Snapshot` from the TRUD RF2 release, filter to
   `typeId = 116680003`, keep `active = 1`.
2. Assert acyclicity (it should hold; verify anyway — it is a two-line check and
   the brief's validator requires it).
3. Pick our ~30–40 leaf conditions and the ~8–12 categories above them.
4. Take the **induced subposet** over that selection, then reduce to the
   transitive reduction so the DAG has no redundant edges.
5. Choose a spanning arborescence for the breadcrumb — that is the "primary
   parent" the brief asks for. Every other edge is a secondary parent used for
   inference and display.

Pulmonary embolism reaching both a respiratory and a vascular ancestor is not
something we have to model by hand. SNOMED already asserts it.

### 3.2 Where the disjoint-set framing breaks

Union-find requires the sets to be disjoint, and the brief's central data
requirement is that they are not. Pulmonary embolism sits under respiratory *and*
vascular; it appears in the candidate pool for acute cough *and* for chest pain.
Those pools are a **cover, not a partition**. The moment you union-find them, PE's
two branches merge and you have lost exactly the structure the DAG requirement
exists to preserve.

There is a second problem. Grouping conditions by shared symptoms produces one
giant connected component almost immediately — fever, fatigue, cough and pain are
shared across nearly everything in general practice. Connected-component
clustering on a symptom graph has close to zero discriminating power in this
domain.

So: **poset, yes. Disjoint-set union, no.** The right primitives are reachability,
transitive reduction, and least-common-ancestor over a DAG.

### 3.3 The lattice idea is good — as a validator, not a generator

Ordering conditions by symptom-set inclusion is Formal Concept Analysis: a Galois
connection between conditions and features, yielding a concept lattice. It is a
real technique and it is the natural formalisation of what you described.

**It is the wrong way to build the hierarchy.** The clinically useful hierarchy is
aetiological and anatomical — infective, cardiac, embolic, malignant — and that
structure is not recoverable from symptom sets. Pneumonia and PE share pleuritic
pain, breathlessness and tachycardia while sitting in different branches with
completely different management. An extensionally-derived hierarchy would put them
together, which is precisely the error the system exists to prevent. The lattice
also blows up: *n* binary attributes admit up to 2^n concepts, and ours are
multi-valued.

**But run the lattice anyway, as a knowledge-base lint.** Compute the extensional
structure from the authored feature table and compare it against the authored
aetiological DAG. Three checks fall straight out, and nothing else in the
validator catches them:

- **Identical signatures.** Two conditions with the same feature profile can never
  be told apart by any question we can ask. Either a discriminating feature is
  missing or the two should be one node. This generalises the "discrimination
  floor" lint from §5.1 of the architecture position, and it is the more useful
  half of it.
- **Strict subsumption.** If condition A's evidence profile is a subset of B's and
  B's prior is higher, A can never be top-ranked under any evidence whatsoever. It
  is dead weight in the differential, and it is invisible on inspection.
- **Extensional/aetiological divergence.** Where the two structures disagree
  sharply, that is a place to send a clinician. Sometimes it is an authoring
  error; sometimes it is a genuinely hard clinical discrimination that the report
  should be honest about.

That goes in `scripts/validate_kb.py`, which the brief already mandates. Your
maths, pointed at auditing the hierarchy rather than generating it.

### 3.4 Cost of Track A

| Step | Time |
|---|---|
| TRUD account, accept UK + SNOMED Affiliate licences | ~1 day (approval wait) |
| Download UK Clinical Edition RF2 snapshot, load into SQLite | ~3 hours |
| Is-a extraction, acyclicity check, transitive closure | ~3 hours |
| Select subposet, transitive reduction, pick spanning tree | ~half a day, needs clinical eyes |
| **Total** | **~2 days elapsed** |

Note the licence constraint from the source investigation: we store **codes** in
the repo, never SNOMED release files or derived terminology tables.

---

## 4. Track B — rules from NICE

Not a crawl. Roughly fifteen named guidelines across the three complaints (NG12
suspected cancer, CG95 chest pain of recent onset, NG158 venous thromboembolism,
CG150 headaches, and so on). Fetching them takes minutes.

The work is extracting each recommendation **verbatim with its attribution
block**, per the licensing constraint, and confirming it is the current version.
Realistically 2–4 hours per guideline including that check.

**~1 week.**

Start the **NICE syndication API application now, in parallel**, regardless.
Applications are considered monthly, so the lead time is a calendar month. We do
not need it to begin — page fetches are permitted under the open content licence
with attribution — but having a versioned XML feed is much better than fetching
HTML, and the clock only starts once we apply.

---

## 5. Track C — the likelihoods, which is the actual project

Roughly 30 conditions × ~10 stated features ≈ **300 ordinal judgements** (sparse,
per §5.2 of the architecture position — unstated features carry likelihood ratio 1).

| Portion | Method | Cost |
|---|---|---|
| ~45–60 cells, literature-backed | Targeted PMC search, read, extract, record licence | 20–30 min each → **3–4 weeks** |
| ~250 cells, clinician `estimate` | Structured 7-point ordinal elicitation form | 2–3 min each → **~2 days of GP time** |
| Second-clinician review pass | | **~1 week elapsed** |

Two honest caveats.

**The clinician hours are small; the scheduling is not.** Two days of GP time
spread across availability is a multi-week calendar item.

**If no GP is available, this estimate is meaningless.** That is open question 1
from the architecture position, and it is now the single highest-leverage unknown
in the project. Everything in Track C's second row assumes someone qualified is
signing off on ~250 clinical estimates. If the answer is that I author them from
literature and nobody reviews, the honest schedule is longer and the honest claim
about the output is much weaker.

---

## 6. Where the data lives

Two stores, and they must not be confused with each other.

**Acquisition workbench — SQLite, gitignored, throwaway.** Holds the SNOMED
relationship graph, PMC search results and extracted candidate features, and
scratch tables for the lattice checks. It is query-heavy and disposable. This is
the "local DB" your question describes, and it is the right tool for the
extraction phase.

**Authored artefact — YAML under `data/`, exactly as the brief specifies.**
Reviewable by a clinician in a pull request, which a SQLite file is not. This is
what ships, what gets version-hashed into every API response, and what the
Pydantic loader validates at boot.

A script projects workbench → YAML skeleton with codes, hierarchy and empty
likelihood cells, for a human to fill in. **The workbench never becomes the
knowledge base.** If it does, we have lost reviewability, which is the property
the whole curated approach exists to buy.

---

## 7. Timeline

Assuming a GP is available for Track C.

| Elapsed | Milestone |
|---|---|
| Days 1–2 | Track A complete. Skeleton DAG with SNOMED and ICD codes for all three complaints. NICE syndication application submitted. |
| Week 1 | Track B for complaint 1. Validator running: acyclicity, orphans, provenance, the lattice lints. |
| Weeks 2–3 | Track C for complaint 1 (acute cough / breathlessness). Engine, eval harness, **baseline numbers reported before any tuning**. |
| Weeks 4–6 | Complaints 2 and 3. If either requires touching `packages/engine/`, the engine is wrong — per §13 of the brief. |
| Week 7 | Clinical review gate, calibration pass, re-run eval, report the delta. |

**Complaint 1 authored and passing eval: ~3 weeks. All three: ~6–7 weeks.**
Crawling accounts for about two days of that.

---

## 8. What I would do first, on approval

1. Open the TRUD account today — it is the only item with an external approval
   wait on the critical path, and it costs nothing to start.
2. Submit the NICE syndication API application the same day, for the same reason.
3. Build the Track A pipeline and produce the skeleton DAG for all three
   complaints at once. It is the same script three times and it front-loads the
   clinical selection decisions.
4. Run the lattice lints against the empty skeleton to prove the validator works
   before there is anything for it to find.

Steps 1 and 2 are unblocked by every open question in the architecture position
and can start immediately. Step 3 needs the complaint list confirmed — open
question 6.

---

## Sources

- [SNOMED CT UK Clinical Edition, RF2 — NHS TRUD](https://isd.digital.nhs.uk/trud/users/guest/filters/2/categories/26/items/101/licences)
- [Wikidata Query Service](https://query.wikidata.org/sparql) and the [Wikidata API](https://www.wikidata.org/w/api.php) — property [P780 (symptoms and signs)](https://www.wikidata.org/wiki/Property:P780), queried 2026-08-30
- [NICE NG12](https://www.nice.org.uk/guidance/ng12), [NICE syndication API](https://www.nice.org.uk/reusing-our-content/nice-syndication-api)
- [NCBI E-utilities](https://eutils.ncbi.nlm.nih.gov/entrez/eutils/)
- Licensing detail in `phase-0-source-investigation.md`

---

# Revision, 2026-08-30 — NHS, delegation, and the schedule

## 9. Why not the NHS? — I was too quick, and here is the actual structure

I dismissed NHS.uk on the grounds that `robots.txt` disallows `/Conditions/`. That
is true but it answers the wrong question: the NHS *wants* you to use its content,
it just wants you to use the API. So I went and pulled real payloads from the
NHS Digital sandbox to see what is actually in them.

**What an NHS condition document contains.** From
`sandbox/responses/conditions-achalasia-no-params.json` in
`NHSDigital/nhs-website-content-api`:

```
@type:            MedicalWebPage          (schema.org)
license:          https://developer.api.nhs.uk/terms
copyrightHolder:  Crown Copyright
lastReviewed:     ['2023-12-05T...', '2026-12-05T...']
genre:            ['Condition']
mainEntityOfPage: 5 × WebPageElement, each with a headline and HTML text
```

The section headlines are stable across conditions: *Symptoms of X*, *Causes of
X*, *When to get medical help*. Content lives as **HTML prose inside
`WebPageElement.text`**:

> "Not everyone with achalasia will have symptoms. But most people with achalasia
> will find it difficult to swallow food or drink (known as dysphagia). ... Other
> symptoms include: bringing back up undigested food, choking and coughing fits,
> heartburn, chest pain, repeated chest ..."

**What it does not contain.** Checked directly against the payload:

```
mentions snomed: False   mentions icd: False   mentions "code": False
```

No codes. No prevalence. No likelihood strength. No direction — nothing records
that a finding argues *against* a condition. Symptoms are a comma-separated list
inside a sentence, not a field.

**So the corrected verdict is not "no". It is "yes, for the right layer."**

The NHS is the wrong source for likelihoods and base rates because it has none.
It is genuinely the **best available source for two things**, and I underweighted
both:

1. **Safety-netting text.** §7 of the brief requires safety-netting on the report
   screen. The NHS "when to get medical help / call 999" sections are exactly
   that: written for the public, editorially reviewed with dated `lastReviewed`
   fields, Crown Copyright, and API-delivered. Writing that text ourselves would
   be worse and would carry no provenance. **This becomes Track D**, and it is
   about a day of work.
2. **The candidate feature checklist.** Not as clinical assertion, but as the
   scaffold that stops us *omitting* a feature during authoring. Coverage of
   common GP conditions is excellent — the exact inverse of Wikidata's problem.

There is also a licensing win that mirrors the PMC one: every document carries a
`license` field and a `lastReviewed` date. Machine-readable provenance, recorded
per document rather than asserted by an author.

**Two constraints on Track D.** Attribution to the NHS website with the logo
visible and a link back to the source page is required by the syndication terms;
and the terms cap calls at 4,000 per hour, which we are nowhere near. Both are
satisfied by design if we store the source URL alongside the text — which we are
doing anyway.

---

## 10. Delegating to a cheaper model — costed, and the answer is surprising

Yes, and it should be done. But the numbers change the shape of the question.

### 10.1 What a cheap model should do

| Job | Volume | Model | Why it is safe |
|---|---|---|---|
| PMC abstract triage — "does this report diagnostic accuracy, in what setting?" | ~4,000 abstracts | Haiku 4.5 | Binary classification, verifiable by sampling, and a false negative only costs us one more search |
| NHS section extraction — pull *Symptoms of X* / *When to get help* into fields | ~40 documents | Haiku 4.5 | Stable schema, stable headlines, output checked against source by string match |
| NICE recommendation structuring — recommendation blocks into YAML with ids | ~15 guidelines | Sonnet 5 or Opus 5 | Verbatim fidelity is safety-relevant; still trivially cheap at this volume |
| Verbatim-quote verification | every quote | **not a model — code** | `assert quote in source_text`. Exact, free, and a model would be worse at it |

### 10.2 What it costs

Using current pricing — Haiku 4.5 at $1.00/$5.00 per MTok, Sonnet 5 at
$2.00/$10.00, Opus 5 at $5.00/$25.00:

| Job | Tokens | Cost |
|---|---|---|
| 4,000 abstracts triaged (~700 in, ~60 out each) | 2.8M in / 240K out | **~$4.00** on Haiku |
| Same, via Batch API (50% off, not latency-sensitive) | | **~$2.00** |
| 40 NHS documents (~4,000 in, ~500 out each) | 160K / 20K | **~$0.26** |
| 15 NICE guidelines (~15,000 in, ~3,000 out each) | 225K / 45K | **~$0.46** Haiku, **~$2.26** Opus |
| **Whole extraction phase** | | **well under $10** |

**The model spend is not the constraint and never was.** Optimising a ten-dollar
line item is the wrong place to spend effort. Run the NICE structuring on Opus at
`effort: high` because verbatim accuracy on referral criteria is a safety
property and it costs two dollars.

Two things that are worth doing, because they are free rather than because the
bill demands it: put the instruction block behind a cache breakpoint (the
abstract-triage prompt is identical across all 4,000 calls), and use the Batch
API for the triage run since nothing about it is latency-sensitive.

### 10.3 The line the cheap model must not cross

**Retrieval, triage and reshaping — yes. Valuation — never.**

This matters more precisely *because* the calls are cheap. A Haiku call that
emits `"moderately suggestive of PE"` costs about three hundredths of a cent and
lands in the YAML looking exactly like a consultant's judgement. That is the
failure mode, and it is not a cost problem — it is that the knowledge base
silently stops being trustworthy and nobody can tell which cells are real.

**Enforce it in the schema, not by discipline.** Every machine-produced row lands
in the workbench with `origin: machine_candidate`. The loader **rejects** any
assertion in `data/` carrying that origin. Promotion requires a human changing
the field, which shows up in a pull-request diff and is reviewable by the
clinician. It is a one-line check in the validator and it is the difference
between a curated knowledge base and one that merely looks curated.

---

## 11. Why does it take so long? — one cell, worked through

The honest answer is that almost none of the time is extraction, and none of it
is compute. Here is a single cell end to end.

**Cell: does pleuritic chest pain argue for or against PE, and how strongly, in a
UK GP surgery?**

1. Search PMC. ~60 hits. A cheap model triages to ~6 plausibly relevant. *Minutes,
   about a penny.*
2. Read the six. **Five are emergency-department cohorts.** This is where the time
   goes.
3. An LR derived from an ED population **does not transfer to general practice.**
   The patients who reach ED have already been filtered by someone else's triage
   decision, so the spectrum of disease and of alternative diagnoses is different.
   Applying an ED likelihood ratio to a GP prior is *precisely* the error §4 of
   the brief names as the most common way tools like this go wrong.
4. So: find the one primary-care study if it exists, or mark the cell `estimate`
   and take a clinician's ordinal.
5. Record the URL, the licence, the study setting, the population, and the
   caveat.

**20–30 minutes, and step 3 is judgement no model can take over** — deciding
whether a cohort's spectrum is close enough to UK general practice is exactly the
clinical-epidemiological call the tool's credibility rests on. Get it wrong
silently and you have built a confident, well-tested, well-documented system that
is wrong in the specific way that kills people.

**× 300 cells.** That is the six weeks. Not crawling — spectrum-bias adjudication
and expert elicitation, three hundred times.

---

## 12. The lever: scope options, with a recommendation

The schedule is a choice, not a fact. Three honest options.

| Option | Scope | Elapsed | What you give up |
|---|---|---|---|
| **A. Full** | 3 complaints, literature-backed where it exists | ~6–7 weeks | Nothing |
| **B. All-estimate** | 3 complaints, every cell a clinician ordinal, single review pass | **~2–3 weeks** | No published likelihoods. README must say so plainly. |
| **C. One complaint, full depth** | Acute cough / breathlessness only, done properly | ~2 weeks | Two complaints |

**Recommendation: C, then B.** Build complaint 1 to full depth to prove the
vertical, then take the other two on ordinals.

The reasoning is the brief's own §13 — do not build the sophisticated version
until the eval proves the simple one insufficient. **We do not know whether
literature-grade likelihoods actually move top-3 accuracy versus clinician
ordinals.** Nobody does, for this knowledge base. The eval harness answers it
directly: author complaint 1 both ways, measure the delta on the same vignettes,
and let the number decide whether the literature track is worth four more weeks.
If ordinals reach ≥ 0.85 top-3 on their own, the literature track was never
needed and we will have proved it rather than assumed it.

For a demonstration this is almost certainly the right call regardless. What is
being demonstrated is the engine, the question selection, and the interaction —
not the epidemiology. Labelling every cell `estimate` in the UI costs nothing and
is more honest than a knowledge base where 15% of cells are published and the
other 85% quietly are not.

**Two things that cannot be cut in any option:** Track B, the red-flag and
referral rules, and the clinical review gate at §11 of the brief. Those are the
safety path. §13 says never simplify away the red-flag path, and that holds under
every scope choice above.

---

## Sources added in this revision

- [NHSDigital/nhs-website-content-api](https://github.com/NHSDigital/nhs-website-content-api) — sandbox response payloads, inspected 2026-08-30
- [NHS Website Syndicated Content: Standard Licence Terms](https://developer.api.nhs.uk/documents/NHS.UK%20Syndication%20Terms%2030-11-22.pdf) — attribution and the 4,000/hour cap
- [NHS Website Content API v2](https://digital.nhs.uk/developer/api-catalogue/nhs-website-content/v2)
- Model pricing per the `claude-api` skill's current model table (Haiku 4.5 $1/$5, Sonnet 5 $2/$10, Opus 5 $5/$25 per MTok)
