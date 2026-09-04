# CLAUDE.md

Working notes for Claude in this repository. Read this before touching anything.

## What this is

Clinical decision support for UK general practice. It produces a **ranked
differential** with the evidence behind each row. It does not diagnose, and no
output of it should ever read as though it does. The clinician decides.

Nothing in `data/candidates/` is clinically reviewed. It is a scrape plus a
language model. Treat every number it produces as a retrieval statistic, never
as a clinical claim.

## The two tracks

They are separate on purpose and share only `data/shared/variables.yaml`.

**Track A — the hand-authored knowledge base.** 43 conditions across three
complaint pools (acute cough, chest pain, headache), written as reviewable
YAML, validated by Pydantic at load. Small, deliberate, auditable. Lives in
`data/conditions/`, `data/complaints/`, `packages/engine/`.

**Track B — mined retrieval.** 459 NHS condition pages scraped, normalised
into one symptom vocabulary by a flash model, indexed with FAISS, searched by
embedding cosine. Broad, automated, unreviewed. Lives in `scripts/` and
`data/candidates/`.

Track A is what a clinician could sign off. Track B is what covers enough
ground to be useful. Neither is a substitute for the other, and Track B's
output must not be written into Track A's YAML without review.

## The pipeline, in order

Each step caches, so re-running is cheap and safe.

```bash
# 1. Condition and presentation lists from the NHS A-Z, resolved to SNOMED.
uv run --no-sync python scripts/harvest_conditions.py

# 2. Symptom prose from each condition page. Writes only to .workbench/.
uv run --no-sync python scripts/harvest_symptoms.py

# 3. Normalise into the form contract. Only --from-bank exists today;
#    --from-raw is task 6 and reads the scraped prose instead of the old bank.
uv run --no-sync python scripts/normalise_v2.py --from-bank

# 4. Embed the vocabulary into a FAISS index.
uv run --no-sync python scripts/vector_index.py --build

# 5. Search it.
uv run --no-sync python scripts/search.py --explain "dry cough for two months, coughing up blood"
```

`scripts/dataset.py` loads the result as pandas frames; `notebooks/dataset.ipynb`
is the same thing with plots and a similarity analysis. It reads the string
bank by default and the form contract under `--v2`, which is what `search.py`
actually retrieves over, so `--v2` is the one to read when asking why a ranking
came out as it did. `dataset.py --v2 --csv data/candidates/csv-v2/` writes it
out; `data/candidates/csv/` is the same four files over the bank.

## The form contract

The idea Track B rests on, in `scripts/symptom_schema.py`, explained in
`docs/symptom-schema.md`.

A symptom is written as a `Record`: a `concept`, an optional `character` and
`site`, plus facets for onset, duration, severity, progression and polarity.
Only `core_phrase` (character + concept + site) is embedded. The facets are
compared arithmetically.

That split is not a preference, it is forced by two properties of embeddings:

- **Negation does not embed.** "no fever" sits about 0.9 cosine from "fever".
  Polarity has to be arithmetic or absence reads as presence.
- **Time dominates a short string.** In "chest pain for three weeks" the
  duration is half the tokens, so it drowns out the symptom.

The patient's words go through the *same* contract as the corpus. That symmetry
is the whole mechanism: "bringing up blood" and "you may cough up blood" both
normalise to the same core phrase, so the cosine is about blood and sputum
rather than about who was writing.

The schema fixes the **shape** of a symptom, never a list of permitted symptoms.

## Constraints that must not be broken

These are licensing and safety boundaries, not style preferences.

- **NHS prose stays in `.workbench/`**, which is gitignored. Reuse could not be
  confirmed — the pages carry Crown copyright and the content policy is silent.
  What reaches `data/` is names, codes and derived findings, which are facts.
- **TRUD permits storing codes, never release files or derived terminology
  tables.** The 932 MB SNOMED archive stays in `.workbench/trud/`.
- **CKS (`cks.nice.org.uk`) is in `FORBIDDEN_SOURCE_HOSTS`** in
  `packages/engine/dx_engine/kb.py`. Deep-link only. The loader raises if a
  source URL contains it.
- **`fetch_pmc.py` refuses any article without a Creative Commons licence.**
  "Free to read" and "licensed to redistribute" are different things.
- **`GEMINI_API_KEY` and the TRUD key live in the shell and `.env`.** `.env` is
  mode 600 and gitignored. Never let either reach a tracked file.
- **No AI attribution** in commit messages or pull request descriptions.

## Where it actually stands

Tests: seven suites, all passing.

```bash
for t in scripts/test_*.py; do uv run --no-sync python "$t"; done
```

Track B is on branch `rag-retrieval`. Tasks 1–5 of
`docs/plans/2026-09-03-rag-retrieval.md` are done; tasks 1–4 are committed,
task 5's `eval/run_retrieval_eval.py` is measured but uncommitted; tasks 6 and 7
are open. The ledger is `.superpowers/sdd/2026-09-03-rag-retrieval/progress.md`.

Retrieval is now measured. Over the 150 conditions both systems can retrieve,
under one scorer:

| System | top-1 | top-5 | top-10 |
|---|---|---|---|
| String bank (v1), rescored | 59% | 89% | 96% |
| Pass 1, restructured facets | 48% | 75% | 85% |
| Pass 1, seeded at the bank's symptom frequency | 62% | 89% | 93% |
| Condition-profile dense vectors (v2 pool) | 26% | 46% | 59% |

Read rows one to three together. Pass 1 looks eleven points worse and is not:
each system is seeded on the symptoms *it* thinks commonest, and the form
contract merged the vocabulary harder — singletons fell from 71% to 63% of the
vocabulary, mean links per symptom rose 2.26 to 2.95 — so its commonest symptom
is shared by half again as many conditions and the question is harder. Ask both
the same question and they are level. **Never quote the 48/75/85 without the
62/89/93 beside it.** The 75/85/85 that used to stand here is withdrawn: it
predates the deduplication fix and came from a different scorer.

The dense control losing by twenty points is the two-stage design earning
itself.

Paraphrase recovery is 62% exact, 71% same-condition, over 200 symptoms, and
drifts a couple of points run to run. Same-condition credits a near-duplicate
row, which is what `rank()` consumes.

## What is wrong with the data

Say these out loud rather than letting a ranking imply otherwise.

- **No prevalence.** Nothing knows a cold is commoner than lung cancer, so a
  rare condition matching the words outranks a common one matching slightly
  fewer. This is the single largest gap.
- **IDF is not a likelihood ratio.** It says how rare a phrase is in this
  corpus, not how much the symptom shifts the odds in a real population. It
  does fix "cough counts the same as coughing blood", which flat matching could
  not, and that is all it does.
- **Most of the vocabulary does no work.** In the string bank, 926 of 1305
  symptoms appeared in exactly one condition. A symptom unique to one condition
  identifies it and is silent about every other, so it can never rank a
  differential. That is under-merging in the clustering. The form contract
  improved it to 683 of 1087 and is still the majority; task 6 is the next
  chance to reduce it.
- **Retrieval is a hard ceiling — less so than it was.** In the string bank
  top-5 and top-10 were identical, meaning that when the right answer missed
  the first cut, questioning could never recover it. The form contract opened a
  gap (75 to 85 on the shared pool, 71 to 78 on its own), so a second round of
  questioning now has something to find. About 15% of conditions are still
  unreachable at any depth.
- **Umbrella pages rank as diagnoses.** `Cancer` is an NHS hub page, not
  something a GP diagnoses, but it scores like a condition.
- **Around 53 conditions have no symptoms.** Some genuinely have none (high
  cholesterol); the rest are pages the scraper could not read.
- **No severity or urgency.** Nothing marks which symptoms mean "hospital now".
- **Antonyms embed as near-synonyms.** Run the smoke query below and
  `heart-failure` ranks second on a **weight gain** match scoring +5.29 against
  a patient who said they were losing weight. The form contract solved polarity
  (`present` / `absent`) arithmetically but did nothing about opposed concepts,
  because "weight gain" and "weight loss" are one embedding apart the same way
  "fever" and "no fever" were. This is the same bug in a new place and it is
  currently unhandled.
- **A rejected patient record is dropped, and can empty the whole query.**
  `validate()` refuses a concept over two words or one that bundles concepts,
  which is right for the corpus, where it costs one row in 3210. On the query
  side the same rule threw away `blood in urine`, `bowel habit change` and
  `pins and needles`, and "There's blood when I go for a wee" therefore matches
  nothing at all. It caused 4 of 58 paraphrase misses — small, but the failure
  is total when it happens. Splitting a rejected concept on its preposition
  instead of dropping it is the repair, and nobody owns it.
- **Facets are being dropped in normalisation.** In that query "coughing up
  blood" reduces to the bare concept `blood`, losing the sputum entirely, and
  `tongue-tie` then ranks third on "coughing in the throat". Lung cancer does
  not appear at all.

## Working habits that have paid off here

- **Read the data, not just the summary statistics.** Every real defect this
  project has found — the misfiled body systems, the plural stemmer, the
  separability metric testing disjointness instead of difference, the dropped
  cardinal symptoms, the differential lists scraped as symptoms — was caught by
  looking at rows, never by a check passing.
- **Automated passes here produce roughly one error in seven.** Assume yours
  does too, and spot-check before building on the output.
- **Trace a suspicious row back to `.workbench/`** before calling it a bug. Half
  the time the scrape was faithful and the source page was the problem.
- **When a prompt changes, version the cache key.** `normalise_symptoms.py` and
  `normalise_v2.py` both do this. A label cached under old wording silently
  keeps a judgement the new wording would reverse.
- **Use `uv run --no-sync python`.** Bare `python3` misses the venv.
