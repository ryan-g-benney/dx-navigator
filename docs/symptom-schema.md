# The symptom schema

This is the form contract for the retrieval track: the rules a symptom must
follow before it is embedded, and the fields that are compared without being
embedded. It is written to be followed on its own, without reading the code —
an author normalising the bank by hand and a flash model doing the same
should reach the same record from the same sentence.

Implementation: `scripts/symptom_schema.py`. Design rationale: §2 of
`docs/phase-1-rag-retrieval-design.md`.

## 1. What this is for

Both the corpus of mined NHS symptoms and a patient's own words pass through
this contract before anything is compared. Fixing the shape a symptom is
written in is what lets embedding cosine measure the medicine two phrasings
share, rather than measuring how differently they happened to be worded.

## 2. What is embedded, and what never is

Only the **core phrase** — `[character] [concept] [in the <site>]` — is
turned into a vector. Everything else (onset, duration, severity,
progression, polarity) is a sidecar field, compared arithmetically instead.
Two properties of embeddings force that split, not preference:

- **Negation does not embed.** "no fever" sits close to 0.9 cosine from
  "fever". Written into the string, a denial reads to the model as a
  confirmation, so polarity has to live outside the embedded text.
- **Time dominates a short string.** In "chest pain for three weeks" the
  duration is half the tokens. Left in the phrase, it pulls the vector toward
  every other symptom that also lasts three weeks, not toward other chest
  pain.

## 3. The core phrase

| Slot | Rule | Write | Do not write |
|---|---|---|---|
| `character` | Exactly one word, an adjective, first. One colour word, never a compound | `crushing`, `blood-stained`, `yellow` | `crushing, tearing`, `yellowish-green`, `a bad` |
| `concept` | One or two words, the symptom itself, the plain UK term a patient uses | `chest pain`, `breathlessness`, `sputum` | `dyspnoea`, `pains`, `respiratory symptoms` |
| `site` | One word where one exists, otherwise adjective plus noun. The connective is always `in the` | `in the chest`, `in the lower back` | `in the chest area`, `chest region`, `of the chest` |

`character` and `site` are optional; `concept` is not. The three slots
concatenate in that order: `[character] [concept] in the [site]`.

## 4. Register

Every text slot (`concept`, `character`, `site`) is lower case, singular, a
noun phrase, and carries no verb:

- **No second person.** `you feel sick` becomes `nausea`.
- **No hedge.** `a bit of`, `sometimes` are dropped, not softened.
- **No cause.** `low mood from narcolepsy` becomes `low mood`; the cause is
  a different fact than the symptom.
- **No diagnosis, no page furniture.** NHS symptom sections carry
  differential lists alongside the symptoms; `kidney stones` is a diagnosis,
  not a symptom, and is dropped rather than normalised.
- **UK spelling.** `oedema`, not `edema`.

`validate()` in `scripts/symptom_schema.py` enforces the mechanical half of
this — lower case, word counts, and a banned-phrase check for `and`, `or`,
`with`, `you`, `your`, `a bit`, `sometimes` — but the judgement calls (is this
a cause, is this a diagnosis) are for whoever or whatever is filling the
record in, not for the validator.

## 5. One concept per record

A record holds one clinical fact. A bundled phrase such as `confusion and
slurred speech` embeds to the midpoint between the two concepts and matches
neither well, and it cannot be compared: a patient who reports only confusion
would otherwise match the same row as one who reports both. So a bundle is
split into two records before anything else happens to it:

    confusion and slurred speech
        -> confusion
        -> slurred speech

This is the largest single repair the contract makes to the existing bank,
and the reason the second normalisation pass works from raw prose rather than
from the bank's canonical strings — prose still has the sentence boundaries
that show where one concept ends and the next begins.

## 6. Time is a band

Durations and onsets are read off an ordered vocabulary, not a number. The
source text rarely states a number; asking a model to produce one anyway
manufactures a precision the sentence never had, and that invented precision
looks identical to a measured one once it sits in the column. A clinician can
check `three_to_8_weeks` against the source page; nobody can check `47`.
Clinical guidance itself thinks in these bands, so a band is also the unit
the medicine uses, not just a modelling convenience.

| Field | Tokens, in order |
|---|---|
| `duration` | `under_1_day`, `one_to_7_days`, `one_to_3_weeks`, `three_to_8_weeks`, `over_8_weeks`, `unspecified` |
| `onset` | `seconds_to_minutes`, `hours`, `days`, `weeks_or_longer`, `unspecified` |

The four substantive `onset` tokens are copied verbatim from `onset_speed` in
`data/shared/variables.yaml`, so the curated engine and this retrieval track
describe onset the same way. The terminal token is `unspecified` rather than
that file's `unknown`: `unknown` there means a question that has not yet been
asked of a patient, whereas here it means the source text simply never said —
a different fact, and the name this schema uses for it everywhere (also in
`SEVERITIES` and `PROGRESSIONS`) rather than reusing a token that means
something else in the other track.

**Comparison is ordinal distance, not equality.** `band_distance(a, b, order)`
returns how far apart two tokens sit on the vocabulary, scaled to `[0, 1]`:
adjacent bands cost little, the two ends of the scale cost the most. Either
side saying `unspecified` returns `None`, a no-op rather than a mismatch —
most NHS pages state no duration at all, and a silent corpus row must not be
punished against a patient who happened to mention one.

`duration_text` carries the verbatim span the band was read from, such as
"for about two months". It is never embedded and never compared; it exists
purely so a wrong band can be traced back to the words that produced it.

## 7. The remaining sidecar fields

| Field | Values |
|---|---|
| `polarity` | `present`, `absent` |
| `severity` | `mild`, `moderate`, `severe`, `unspecified` |
| `progression` | `improving`, `stable`, `worsening`, `unspecified` |

`polarity` is a genuine enumeration, not a band — it marks whether the
symptom is asserted or denied, a sign rather than a magnitude. `severity`
uses words for the same reason `duration` uses bands rather than numbers: the
source states "severe", never "7/10".

## 8. Worked examples

Every "bank today" row below is a real `canonical` value from
`data/candidates/symptom-bank.tsv`, quoted unmodified. The bank itself is not
touched by this task; these are what the contract would produce from that
text.

| Bank today | Becomes | Rule demonstrated |
|---|---|---|
| `confusion and slurred speech` | `confusion`; `slurred speech` | one concept per record (§5) |
| `vision loss or blurring` | `vision loss`; `blurred vision` | `or` also bundles; each half becomes its own noun phrase |
| `numbness and weakness in hands` | `numbness in the hand`; `weakness in the hand` | splitting plus `site`, singular, connective `in the` |
| `low mood from narcolepsy` | `low mood` | no cause (§4) |
| `rashes ulcers and spots` | `rash`; `ulcer`; `spot` | splitting a three-way bundle, plural to singular |
| `greasy scales on scalp and face` | `greasy scale in the scalp`; `greasy scale in the face` | `character` + `site`, and a site conjunction still splits |
| `swollen fingers and toes` | `swelling in the finger`; `swelling in the toe` | adjective-as-symptom recast as `concept` + `site` |
| `high temperature and vomiting` | `fever`; `vomiting` | plain UK term the patient uses (§3), plus splitting |
| `severe sharp pain` | `sharp pain` with `severity: severe` | magnitude moves out of the phrase into a sidecar field |
| `mild fever` | `fever` with `severity: mild` | same rule, opposite end of the scale |

A ninth, hypothetical example ties duration back to source text: "coughing up
blood for two months, losing weight" becomes `blood-stained sputum` with
`duration: three_to_8_weeks` and `duration_text: "for two months"`, plus a
separate `weight loss` record. The patient side runs through the identical
contract, which is the mechanism that makes retrieval work at all: "I have
been bringing up blood" and "you may cough up blood" both normalise to
`blood-stained sputum`, so the cosine between them measures blood and sputum,
not who was writing.
