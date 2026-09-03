# Phase 1 — Retrieval by normalised symptom, with embeddings

**Date:** 2026-09-03
**Status:** approved. Supersedes nothing; this is the second track alongside the
curated engine in `packages/engine/`, not a replacement for it.

The claim under test: **a retrieval system over normalised symptoms can take a
patient's own words and return a useful shortlist of conditions.** The mined
dataset already ranks conditions by free-text search, but it compares raw
strings, so a match depends on wording as much as on medicine. This phase
replaces the string with a form contract and measures whether that helps.

---

## 1. What is wrong today

`data/candidates/symptom-bank.tsv` holds 1305 canonical symptoms, each a free
phrase produced by clustering NHS wordings and asking a flash model to name the
cluster. The names bundle several concepts into one token:

    confusion and slurred speech
    numbness and weakness in hands
    rashes ulcers and spots
    low mood from narcolepsy
    greasy scales on scalp and face

A bundled phrase embeds to the midpoint between two clusters and matches
neither well. It also cannot be compared: a patient who reports only confusion
matches the same cell as one who reports both. Duration, severity and colour
appear inside some names and not others, so two records that state the same
clinical fact sit at different points in vector space for reasons that are
about writing rather than about the patient.

## 2. The schema is a form contract, not a vocabulary

Comparison is done by embedding cosine. Closed value lists would discard the
semantics that makes cosine work and would need an ontology nobody can finish.
What makes two phrasings of one symptom land together is a shared grammatical
shape and a shared register. The schema therefore specifies **how a symptom is
written**, and both the corpus and the patient's text pass through it.

### 2.1 What is embedded, and what never is

Embed the core phrase only:

    [character] [concept] [in the <site>]

Polarity, onset, duration, severity and progression are sidecar fields,
compared arithmetically. Two properties of embeddings force this:

- **Negation does not embed.** `no fever` sits near 0.9 cosine from `fever`.
  Written into the string, a denial reads as a confirmation.
- **Time dominates a short string.** In `chest pain for three weeks` the
  duration is half the tokens, so the vector drifts toward every other symptom
  that lasts three weeks.

### 2.2 The core phrase

Lower case, singular, a noun phrase, no verb, no second person, UK spelling.

| Slot | Rule | Write | Do not write |
|---|---|---|---|
| `character` | exactly one word, an adjective, first. One colour word, never a compound | `crushing`, `blood-stained`, `yellow` | `crushing, tearing`, `yellowish-green`, `a bad` |
| `concept` | one or two words, the symptom itself, the plain UK term a patient uses | `chest pain`, `breathlessness`, `sputum` | `dyspnoea`, `pains`, `respiratory symptoms` |
| `site` | one word where one exists, otherwise adjective plus noun. The connective is always `in the` | `in the chest`, `in the lower back` | `in the chest area`, `chest region`, `of the chest` |

Applying everywhere: no second person (`you feel sick` becomes `nausea`), no
hedge (`a bit of`, `sometimes`), no cause (`low mood from narcolepsy` becomes
`low mood`), no diagnosis, no page furniture. NHS symptom sections carry
differential lists, so `kidney stones` is not a symptom and must be dropped.

**One concept per record.** `confusion and slurred speech` becomes two records.
This is the largest single repair and the reason pass 2 works from raw prose.

### 2.3 Time is a band

Bands, not numbers. The source rarely states a number, so a numeric field makes
the model invent precision that the text does not contain, and invented
precision cannot be distinguished from measured precision once it is in the
column. Two extractions of "a couple of months" give 60 and 56, and that
difference is prompt noise scored as clinical difference. A clinician can check
`three_to_8_weeks` against the page; nobody can check `47`. Clinical thresholds
are bands in the guidance itself, so the band is also the unit the medicine
uses.

| Field | Tokens, in order |
|---|---|
| `duration` | `under_1_day`, `one_to_7_days`, `one_to_3_weeks`, `three_to_8_weeks`, `over_8_weeks`, `unspecified` |
| `onset` | `seconds_to_minutes`, `hours`, `days`, `weeks_or_longer`, `unspecified` |

`onset` is taken verbatim from `data/shared/variables.yaml`, so the two tracks
share one vocabulary. Track A's `cough_duration: under_3_weeks` is the union of
the first three duration bands.

Comparison is ordinal distance between band positions, not equality. Adjacent
bands cost little and distant bands cost a lot. `unspecified` on either side is
a no-op and never a mismatch, which is the common case: most NHS pages state no
duration at all.

`duration_text` carries the verbatim span the band came from, such as "for
about two months". It is never embedded and never compared. It exists so a
wrong band can be traced to the words that produced it.

### 2.4 The remaining sidecar fields

| Field | Values |
|---|---|
| `polarity` | `present`, `absent` |
| `severity` | `mild`, `moderate`, `severe`, `unspecified` |
| `progression` | `improving`, `stable`, `worsening`, `unspecified` |

`polarity` is a genuine enumeration because it marks a sign rather than a
meaning. Severity uses words for the same reason duration does.

### 2.5 Worked examples

| Bank today | Becomes |
|---|---|
| `confusion and slurred speech` | `confusion`; `slurred speech` |
| `numbness and weakness in hands` | `numbness in the hand`; `weakness in the hand` |
| `low mood from narcolepsy` | `low mood` |
| `rashes ulcers and spots` | `rash`; `ulcer`; `spot` |
| `vision loss or blurring` | `vision loss`; `blurred vision` |
| "coughing up blood for two months, losing weight" | `blood-stained sputum` with `duration: three_to_8_weeks`; `weight loss` |

The patient side runs the same contract under the same rules. That symmetry is
the mechanism: "I have been bringing up blood" and "you may cough up blood"
both normalise to `blood-stained sputum`, so the cosine between them measures
blood and sputum rather than who was writing.

The contract ships as `docs/symptom-schema.md`, written as instructions an
author or a model can follow, with the worked examples above.

## 3. Data model

A facet belongs to a condition's assertion of a symptom, not to the symptom.
Lung cancer's cough is chronic and croup's is not, so the two files split:

    symptoms-v2.tsv            symptom_id, core_phrase, character, concept,
                               site, n_conditions
    condition-symptoms-v2.tsv  condition, symptom_id, onset, duration,
                               duration_text, severity, progression, polarity

Only `core_phrase` is embedded. The existing `symptom-bank.tsv` and
`condition-symptoms.tsv` stay untouched as the baseline the evaluation compares
against.

## 4. Pipeline

**Pass 1, restructure the existing bank.** The 1305 canonical strings go to the
flash model in batches of 40 and come back as records. Roughly 35 calls. A
symptom that splits into two links its conditions to both. This gives a working
end-to-end demonstration on the first day and a first evaluation row.

**Pass 2, normalise from raw prose.** One flash call per condition over the 459
files in `.workbench/nhs/conditions/`, emitting records directly. Prose is
where the facets live: "a cough that lasts more than 3 weeks" yields a duration
band only while the sentence is still visible, which pass 1 cannot see. Core
phrases then cluster by embedding cosine at the existing 0.88 threshold to
build the vocabulary.

Both passes reuse `scripts/_gemini.py` for cached embeddings and flash calls,
and `cluster()` from `scripts/normalise_symptoms.py`. New code is two prompts
and a record writer.

## 5. Index and query

The index is `faiss.IndexFlatIP` over unit-normalised core-phrase vectors, so
inner product is cosine. Exact search, not HNSW: 1300 by 768 is four megabytes,
an exhaustive scan is immediate, and an exact index has no recall loss to
explain. FAISS stores no payload, so row order in the index equals row order in
`symptoms-v2.tsv`, and that is the join.

The query path:

1. Free text goes to one flash call carrying the record schema and returns
   patient records under the same contract as the corpus.
2. Each core phrase is embedded and searched with `k=5`; hits below 0.80
   cosine are dropped, matching the existing `MATCH` constant.
3. Each matched symptom contributes `+idf` when polarity is `present` and
   `-0.7 x idf` when it is `absent`, reusing `ABSENT_WEIGHT`.
4. Facet agreement scales the contribution. The same concept with a distant
   duration band multiplies down toward a floor of 0.4. A facet mismatch never
   goes negative, because it is weaker evidence rather than counter-evidence.
5. Conditions are scored by sparse dot product with length normalisation at
   `alpha = 0.25`, the value already fitted in `triage_poc.py`.
6. The top ten print with the symptoms that put them there and what each
   contributed.

The interface is `scripts/search.py "free text" [--n 10] [--explain]`, and a
notebook cell calls the same function.

Inverse document frequency is a corpus statistic standing in for a likelihood
ratio. It is not a published figure and the output must not present it as one.

## 6. Evaluation

Two measurements and one transcript.

**Retrieval.** The held-out design already in `triage_poc.py --eval`: seed a
condition on two of its own symptoms, ask nothing, and record where it comes
back. The same 150 conditions and the same seed across four systems.

| System | top-1 | top-5 | top-10 |
|---|---|---|---|
| Current string bank | 75% | 85% | 85% |
| Pass 1, restructured facets | | | |
| Pass 2, normalised from raw | | | |
| Condition-profile dense vectors | | | |

The blank cells are the result of the phase. The first row is the figure
already measured in `scripts/triage_poc.py` at `alpha = 0.25`.

The fourth row is the one-vector-per-condition alternative, built as a
forty-line baseline. It has no per-row evidence, so it is a control rather than
a candidate.

**Paraphrase recovery.** Two hundred corpus symptoms are rewritten by the flash
model as a patient would say them, run through the query path, and checked
against the symptom they came from. This measures the symmetry claim in §2.5
directly, and the current bank has no equivalent figure.

**Transcript.** Six hand-written patient descriptions with their normalised
records and their top ten, committed as markdown.

Both figures carry the warning `eval/run_eval.py` already prints. The corpus,
the paraphrases and the extraction all come from one scrape and one model, so
these measure retrieval and internal consistency, not clinical accuracy.

## 7. Scope

In scope: the schema, both normalisation passes, the index, the query path, the
command-line and notebook interface, and the evaluation above.

Out of scope: the question-asking loop in `triage_poc.py`, prevalence, red
flags, safety-netting, and any connection to the curated engine. This track
retrieves; it does not advise. The output is a shortlist for a clinician to
read, and the interface must say so.

## 8. Assumptions

1. Gemini remains the extraction and embedding model. Every call is cached in
   `.workbench/`, which is gitignored.
2. No real patient data. The transcript vignettes are written by hand.
3. The NHS scrape stays in `.workbench/`; only normalised clinical terms reach
   `data/`, as in the existing pipeline.
4. The licensing question in `docs/source-catalogue.md` is unresolved and this
   phase does not change it.

## 9. Open questions

1. The facet floor of 0.4 in §5 is a guess. It should be fitted against the
   paraphrase evaluation rather than left as a constant nobody revisits.
2. Pass 2 costs one flash call per condition and may find facets that pass 1
   cannot. If the evaluation shows no gain, pass 1 is the cheaper thing to
   keep, and the comparison is the reason both are built.
3. Whether the site slot needs a controlled list after all. The form rule may
   not be enough to keep `tummy` and `abdomen` together, and the evaluation
   will show it.
