# Normalised-symptom retrieval — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Take a patient's free text, normalise it into structured symptom records, and return the ten conditions nearest in embedding space, with the evidence for each.

**Architecture:** A form contract (`docs/symptom-schema.md`) governs how every symptom is written. Both the NHS corpus and the patient's text pass through it. Only the core phrase is embedded; onset, duration, severity and polarity are compared arithmetically. A FAISS flat index over ~1300 core phrases turns free text into matched symptoms; conditions are then scored by inverse-document-frequency weight in sparse symptom space.

**Tech Stack:** Python 3.11+, `uv`, numpy, pandas, faiss-cpu, Gemini through the existing `scripts/_gemini.py` (cached embeddings and flash calls).

**Spec:** `docs/phase-1-rag-retrieval-design.md`

## Global Constraints

- Tests are assert-based self-check scripts, run with `uv run python scripts/test_*.py`. No pytest, no fixtures. This is the existing convention (`scripts/test_kb.py`, `scripts/test_rules.py`).
- Nothing derived from NHS prose reaches `data/` except normalised clinical terms. Raw prose, embeddings and the FAISS index stay in `.workbench/`, which is gitignored.
- `data/candidates/symptom-bank.tsv` and `data/candidates/condition-symptoms.tsv` are never modified. They are the evaluation baseline.
- Band vocabularies are fixed and ordered: `duration` is `under_1_day, one_to_7_days, one_to_3_weeks, three_to_8_weeks, over_8_weeks, unspecified`; `onset` is `seconds_to_minutes, hours, days, weeks_or_longer, unspecified` (verbatim from `data/shared/variables.yaml`).
- Existing tuned constants are reused, not re-derived: `MATCH = 0.80`, `ABSENT_WEIGHT = 0.7`, `LENGTH_ALPHA = 0.25` (all from `scripts/triage_poc.py`), cluster threshold `0.88` (from `scripts/normalise_symptoms.py`).
- Inverse document frequency is a corpus statistic, not a likelihood ratio. Any output that shows it says so.
- Every prompt that reaches the flash model carries a `PROMPT_VERSION` string in its cache key, as `scripts/normalise_symptoms.py` already does.

---

### Task 1: The schema module and the contract document

**Files:**
- Create: `scripts/symptom_schema.py`
- Create: `scripts/test_symptom_schema.py`
- Create: `docs/symptom-schema.md`

**Interfaces:**
- Consumes: nothing.
- Produces: `Record` (frozen dataclass), `Record.core_phrase` property, `validate(record) -> None` raising `ValueError`, `band_distance(a, b, order) -> float | None`, `facet_multiplier(corpus, patient) -> float`, the ordered lists `DURATIONS`, `ONSETS`, `SEVERITIES`, `PROGRESSIONS`, and `GEMINI_SCHEMA` (the JSON schema both normalisation passes hand to the flash model).

- [ ] **Step 1: Write the failing test**

```python
#!/usr/bin/env python3
"""Self-check for the symptom form contract. Run: uv run python scripts/test_symptom_schema.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from symptom_schema import (  # noqa: E402
    DURATIONS, ONSETS, FACET_FLOOR, Record, band_distance, facet_multiplier, validate,
)


def rejects(fn, why: str) -> None:
    try:
        fn()
    except ValueError:
        return
    raise AssertionError(f"should have been rejected: {why}")


def test_core_phrase():
    assert Record(concept="chest pain").core_phrase == "chest pain"
    assert Record(concept="sputum", character="blood-stained").core_phrase == "blood-stained sputum"
    assert Record(concept="numbness", site="hand").core_phrase == "numbness in the hand"
    assert (Record(concept="pain", character="crushing", site="chest").core_phrase
            == "crushing pain in the chest")


def test_form_rules():
    validate(Record(concept="chest pain", character="crushing", site="lower back"))
    rejects(lambda: validate(Record(concept="confusion and slurred speech")),
            "two concepts in one record")
    rejects(lambda: validate(Record(concept="vision loss or blurring")), "or in the concept")
    rejects(lambda: validate(Record(concept="Chest Pain")), "not lower case")
    rejects(lambda: validate(Record(concept="you feel sick")), "second person")
    rejects(lambda: validate(Record(concept="pain", character="crushing tearing")),
            "character must be one word")
    rejects(lambda: validate(Record(concept="respiratory tract symptoms of infection")),
            "concept over two words")
    rejects(lambda: validate(Record(concept="cough", duration="two months")),
            "duration not a band token")
    rejects(lambda: validate(Record(concept="cough", polarity="maybe")), "polarity not a token")


def test_band_distance():
    # unspecified on either side is a no-op, never a mismatch
    assert band_distance("unspecified", "over_8_weeks", DURATIONS) is None
    assert band_distance("hours", "unspecified", ONSETS) is None
    assert band_distance("hours", "hours", ONSETS) == 0.0
    assert band_distance("under_1_day", "over_8_weeks", DURATIONS) == 1.0
    near = band_distance("one_to_3_weeks", "three_to_8_weeks", DURATIONS)
    far = band_distance("under_1_day", "three_to_8_weeks", DURATIONS)
    assert 0.0 < near < far < 1.0


def test_facet_multiplier():
    cough = Record(concept="cough")
    chronic = Record(concept="cough", duration="over_8_weeks")
    acute = Record(concept="cough", duration="under_1_day")
    assert facet_multiplier(cough, chronic) == 1.0            # corpus silent, no penalty
    assert facet_multiplier(chronic, chronic) == 1.0
    assert facet_multiplier(chronic, acute) == FACET_FLOOR    # opposite ends, floored
    assert 0 < FACET_FLOOR < 1
    mid = facet_multiplier(chronic, Record(concept="cough", duration="three_to_8_weeks"))
    assert FACET_FLOOR < mid < 1.0                            # a mismatch is never negative


for fn in (test_core_phrase, test_form_rules, test_band_distance, test_facet_multiplier):
    fn()
    print(f"  ok  {fn.__name__}")
print("symptom schema: all checks passed")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run python scripts/test_symptom_schema.py`
Expected: `ModuleNotFoundError: No module named 'symptom_schema'`

- [ ] **Step 3: Write the module**

```python
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
```

- [ ] **Step 4: Run the test and watch it pass**

Run: `uv run python scripts/test_symptom_schema.py`
Expected: five `ok` lines, then `symptom schema: all checks passed`

- [ ] **Step 5: Write the contract document**

Create `docs/symptom-schema.md`. It is the prose an author or a model follows, so it must be readable on its own. Copy §2 of `docs/phase-1-rag-retrieval-design.md` into it and add, for each rule, one example drawn from the real bank. Required sections, in this order:

1. What the contract is for, in two sentences: both the corpus and the patient's words pass through it so that cosine measures medicine rather than phrasing.
2. What is embedded and what is not, with the two embedding failures (negation, time) as the justification.
3. The core phrase table: `character` one word, `concept` one or two words, `site` one word or adjective-plus-noun, connective always `in the`.
4. The register rules: lower case, singular, noun phrase, no verb, no second person, UK spelling, no hedge, no cause, no diagnosis.
5. One concept per record, with `confusion and slurred speech` shown splitting into two.
6. Time as a band, with both ordered vocabularies, the ordinal-distance rule, `unspecified` as a no-op, and `duration_text` as the verbatim span kept for audit.
7. The remaining sidecar fields.
8. A worked table of at least eight before-and-after rows taken from `data/candidates/symptom-bank.tsv`.

- [ ] **Step 6: Commit**

```bash
git add scripts/symptom_schema.py scripts/test_symptom_schema.py docs/symptom-schema.md
git commit -m "Fix the form a symptom is written in"
```

---

### Task 2: Restructure the existing bank into records

**Files:**
- Create: `scripts/normalise_v2.py`
- Create: `data/candidates/symptoms-v2.tsv`
- Create: `data/candidates/condition-symptoms-v2.tsv`

**Interfaces:**
- Consumes: `Record`, `validate`, `GEMINI_SCHEMA` from Task 1; `scripts/_gemini.py` `ask()`.
- Produces: `write_tables(links) -> None` where `links` is `list[tuple[str, Record]]` of `(condition_slug, record)`; the two TSV files with the header rows given below; `--from-bank` on the command line.

The vocabulary and the assertion split across two files, because a facet belongs to a condition's claim about a symptom rather than to the symptom itself. Lung cancer's cough is chronic; croup's is not.

```
symptoms-v2.tsv            symptom_id  core_phrase  character  concept  site  n_conditions
condition-symptoms-v2.tsv  condition  symptom_id  onset  duration  duration_text  severity  progression  polarity
```

- [ ] **Step 1: Write the script**

```python
#!/usr/bin/env python3
"""Rewrite the mined symptoms under the form contract.

Two passes, and the difference between them is what they can see:

  --from-bank  the 1305 canonical strings. Splits bundled phrases, which is
               most of the repair, but cannot recover a facet the string never
               carried.
  --from-raw   the scraped prose in .workbench/nhs/conditions/. One call per
               condition, so "a cough lasting more than 3 weeks" still has its
               sentence and yields a duration band.

Both write the same two tables. Raw prose stays in .workbench/; only the
normalised clinical terms reach data/.

    normalise_v2.py --from-bank
    normalise_v2.py --from-raw [--limit 20]
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import _gemini as G  # noqa: E402
from symptom_schema import GEMINI_SCHEMA, Record, validate  # noqa: E402

CAND = ROOT / "data" / "candidates"
BANK = CAND / "symptom-bank.tsv"
LINKS = CAND / "condition-symptoms.tsv"
OUT_SYMPTOMS = CAND / "symptoms-v2.tsv"
OUT_LINKS = CAND / "condition-symptoms-v2.tsv"

BATCH = 40
PROMPT_VERSION = "1"

RULES = """Rewrite each symptom under a fixed form contract.

Core phrase slots:
- concept: one or two words, the symptom itself, the plain UK term a patient
  would use. Singular. Never Latin: "shortness of breath" not "dyspnoea".
- character: at most ONE word, an adjective. One colour word, never a
  compound: "yellow", not "yellowish-green".
- site: one word where one exists ("chest", "hand"), otherwise two
  ("lower back"). Never "area" or "region".

Rules:
- ONE concept per record. Split anything bundled: "confusion and slurred
  speech" becomes two records, "rashes ulcers and spots" becomes three.
- Lower case. No second person: "you feel sick" becomes "nausea".
- Drop the cause: "low mood from narcolepsy" becomes "low mood".
- Drop hedges: "a bit of", "sometimes", "a bad".
- Emit nothing for a named disease. NHS symptom sections list what an illness
  is confused with; "kidney stones" is not a symptom.
- Emit nothing for treatments, risk factors, statistics or page furniture.
- Set a band only when the text states it. Otherwise leave it unspecified.
  Never guess a duration.
- duration_text is the words the band came from, quoted, or empty."""


def _flash(payload: str) -> list[dict]:
    res = G.ask(f"{RULES}\n\nVERSION {PROMPT_VERSION}\n\n{payload}", schema=GEMINI_SCHEMA)
    return res.get("records", [])


def _record(raw: dict) -> Record | None:
    r = Record(
        concept=raw.get("concept", "").strip().lower(),
        character=raw.get("character", "").strip().lower(),
        site=raw.get("site", "").strip().lower(),
        onset=raw.get("onset", "unspecified"),
        duration=raw.get("duration", "unspecified"),
        duration_text=raw.get("duration_text", "").strip(),
        severity=raw.get("severity", "unspecified"),
        progression=raw.get("progression", "unspecified"),
        polarity=raw.get("polarity", "present"),
    )
    try:
        validate(r)
    except ValueError as e:
        print(f"  dropped {r.concept!r}: {e}", file=sys.stderr)
        return None
    return r


def from_bank() -> list[tuple[str, Record]]:
    """Pass 1. Rewrite each canonical string; every condition linked to the old
    symptom links to each record the string splits into."""
    bank = {int(i): name for i, name, _ in
            (ln.split("\t") for ln in BANK.read_text().splitlines()[1:] if ln)}
    old_links: dict[int, list[str]] = {}
    for ln in LINKS.read_text().splitlines()[1:]:
        if ln:
            cond, sid = ln.split("\t")
            old_links.setdefault(int(sid), []).append(cond)

    ids = sorted(bank)
    out: list[tuple[str, Record]] = []
    for start in range(0, len(ids), BATCH):
        chunk = ids[start:start + BATCH]
        payload = "Symptoms:\n" + "\n".join(f"[{i}] {bank[i]}" for i in chunk)
        # The model returns records in order; a split phrase yields several in a
        # row, so the id is carried in the concept-free `duration_text` slot at
        # our cost. Simpler: one call per chunk of ONE symptom is too many calls,
        # so ask for the id back explicitly.
        for raw in _flash(payload + "\n\nPrefix each record's concept with its "
                                    "bracketed id, exactly as given."):
            concept = raw.get("concept", "")
            if not concept.startswith("["):
                continue
            sid_text, _, rest = concept.partition("]")
            try:
                sid = int(sid_text.lstrip("["))
            except ValueError:
                continue
            rec = _record({**raw, "concept": rest.strip()})
            if rec is None:
                continue
            for cond in old_links.get(sid, []):
                out.append((cond, rec))
        print(f"  {min(start + BATCH, len(ids))}/{len(ids)} symptoms", flush=True)
    return out


def write_tables(links: list[tuple[str, Record]]) -> None:
    phrases: dict[str, Record] = {}
    for _, r in links:
        phrases.setdefault(r.core_phrase, r)
    ids = {p: i for i, p in enumerate(sorted(phrases))}

    counts: dict[str, set[str]] = {}
    for cond, r in links:
        counts.setdefault(r.core_phrase, set()).add(cond)

    OUT_SYMPTOMS.write_text(
        "symptom_id\tcore_phrase\tcharacter\tconcept\tsite\tn_conditions\n" + "".join(
            f"{ids[p]}\t{p}\t{r.character}\t{r.concept}\t{r.site}\t{len(counts[p])}\n"
            for p, r in sorted(phrases.items())))

    seen: set[tuple[str, int]] = set()
    rows = []
    for cond, r in sorted(links, key=lambda cr: (cr[0], ids[cr[1].core_phrase])):
        key = (cond, ids[r.core_phrase])
        if key in seen:
            continue
        seen.add(key)
        rows.append(f"{cond}\t{ids[r.core_phrase]}\t{r.onset}\t{r.duration}\t"
                    f"{r.duration_text}\t{r.severity}\t{r.progression}\t{r.polarity}\n")
    OUT_LINKS.write_text(
        "condition\tsymptom_id\tonset\tduration\tduration_text\tseverity\t"
        "progression\tpolarity\n" + "".join(rows))

    print(f"{len(phrases)} symptoms, {len(rows)} links")


def main() -> None:
    if "--from-bank" in sys.argv:
        write_tables(from_bank())
        return
    raise SystemExit("give --from-bank (--from-raw arrives in task 6)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke-test the writer without spending a call**

Run:

```bash
uv run python -c "
import sys; sys.path.insert(0, 'scripts')
from symptom_schema import Record
from normalise_v2 import write_tables
write_tables([('lung-cancer', Record(concept='sputum', character='blood-stained', duration='three_to_8_weeks')),
              ('lung-cancer', Record(concept='weight loss')),
              ('asthma', Record(concept='cough', duration='over_8_weeks'))])
"
head -3 data/candidates/symptoms-v2.tsv data/candidates/condition-symptoms-v2.tsv
```

Expected: `3 symptoms, 3 links`, and both files carry their header row plus rows whose `symptom_id` values agree across the two files.

- [ ] **Step 3: Run the real pass**

Run: `uv run python scripts/normalise_v2.py --from-bank`
Expected: roughly 33 batches, a count above 1305 (bundles split, so records outnumber the strings they came from), and dropped-record warnings on stderr for the diseases and page furniture the contract rejects.

- [ ] **Step 4: Eyeball the split**

Run:

```bash
grep -E "confusion|slurred|numbness|rash" data/candidates/symptoms-v2.tsv | head -20
```

Expected: separate rows for `confusion` and `slurred speech`; no row containing ` and `.

- [ ] **Step 5: Commit**

```bash
git add scripts/normalise_v2.py data/candidates/symptoms-v2.tsv data/candidates/condition-symptoms-v2.tsv
git commit -m "Rewrite the mined symptoms under the form contract"
```

---

### Task 3: The FAISS index

**Files:**
- Create: `scripts/vector_index.py`
- Create: `scripts/test_vector_index.py`
- Modify: `pyproject.toml` (add `faiss-cpu`)

**Interfaces:**
- Consumes: `scripts/_gemini.py` `embed()`.
- Produces: `build(phrases: list[str], path: Path) -> None`, `load(path: Path) -> faiss.Index`, `query(index, texts: list[str], k: int = 5) -> list[list[tuple[int, float]]]` returning `(row_id, cosine)` pairs per input text, and `INDEX_PATH = ROOT/".workbench"/"index"/"symptoms-v2.faiss"`.

- [ ] **Step 1: Add the dependency**

Run: `uv add faiss-cpu`
Expected: `pyproject.toml` gains `faiss-cpu` and `uv.lock` updates.

- [ ] **Step 2: Write the failing test**

```python
#!/usr/bin/env python3
"""Self-check for the vector index. No network: vectors are supplied directly.
Run: uv run python scripts/test_vector_index.py"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vector_index as V  # noqa: E402


def test_search_is_cosine_and_ordered():
    vecs = np.array([[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]], dtype="float32")
    index = V.from_vectors(vecs)
    hits = V.search(index, np.array([[1.0, 0.0]], dtype="float32"), k=3)[0]
    ids = [i for i, _ in hits]
    assert ids[0] == 0, ids
    assert ids[1] == 1, ids
    assert abs(hits[0][1] - 1.0) < 1e-5, hits[0]
    assert hits[0][1] > hits[1][1] > hits[2][1]
    assert hits[2][1] < 0.2, "orthogonal vector should score near zero"


def test_roundtrip(tmp: Path):
    vecs = np.array([[1.0, 0.0], [0.0, 1.0]], dtype="float32")
    path = tmp / "t.faiss"
    V.save(V.from_vectors(vecs), path)
    hits = V.search(V.load(path), np.array([[0.0, 1.0]], dtype="float32"), k=1)[0]
    assert hits[0][0] == 1, hits


import tempfile  # noqa: E402

test_search_is_cosine_and_ordered()
print("  ok  test_search_is_cosine_and_ordered")
with tempfile.TemporaryDirectory() as d:
    test_roundtrip(Path(d))
print("  ok  test_roundtrip")
print("vector index: all checks passed")
```

- [ ] **Step 3: Run it and watch it fail**

Run: `uv run python scripts/test_vector_index.py`
Expected: `ModuleNotFoundError: No module named 'vector_index'`

- [ ] **Step 4: Write the module**

```python
#!/usr/bin/env python3
"""FAISS over the normalised symptom vocabulary.

IndexFlatIP on unit-normalised vectors, so inner product is cosine. Exact,
not HNSW: 1300 x 768 floats is four megabytes, an exhaustive scan is
immediate, and an exact index has no recall loss to caveat.

FAISS stores no payload. Row order in the index is row order in
data/candidates/symptoms-v2.tsv, and that is the only join.

    vector_index.py --build     embed the vocabulary and write the index
"""
from __future__ import annotations

import sys
from pathlib import Path

import faiss
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

INDEX_PATH = ROOT / ".workbench" / "index" / "symptoms-v2.faiss"
SYMPTOMS = ROOT / "data" / "candidates" / "symptoms-v2.tsv"


def _unit(vecs: np.ndarray) -> np.ndarray:
    v = np.ascontiguousarray(vecs, dtype="float32")
    faiss.normalize_L2(v)
    return v


def from_vectors(vecs: np.ndarray) -> faiss.Index:
    v = _unit(vecs)
    index = faiss.IndexFlatIP(v.shape[1])
    index.add(v)
    return index


def search(index: faiss.Index, queries: np.ndarray, k: int = 5
           ) -> list[list[tuple[int, float]]]:
    scores, ids = index.search(_unit(queries), k)
    return [[(int(i), float(s)) for i, s in zip(row_i, row_s) if i != -1]
            for row_i, row_s in zip(ids, scores)]


def save(index: faiss.Index, path: Path = INDEX_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(path))


def load(path: Path = INDEX_PATH) -> faiss.Index:
    if not path.exists():
        raise SystemExit(f"no index at {path}; run vector_index.py --build")
    return faiss.read_index(str(path))


def phrases() -> list[str]:
    """Core phrases in row order. The index and this list must agree."""
    return [ln.split("\t")[1] for ln in SYMPTOMS.read_text().splitlines()[1:] if ln]


def build() -> None:
    import _gemini as G

    texts = phrases()
    vecs = np.array(G.embed(texts, progress=True), dtype="float32")
    save(from_vectors(vecs))
    print(f"{len(texts)} phrases indexed at {INDEX_PATH}")


if __name__ == "__main__":
    if "--build" in sys.argv:
        build()
    else:
        raise SystemExit("give --build")
```

- [ ] **Step 5: Run the test and watch it pass**

Run: `uv run python scripts/test_vector_index.py`
Expected: two `ok` lines, then `vector index: all checks passed`

- [ ] **Step 6: Build the real index**

Run: `uv run python scripts/vector_index.py --build`
Expected: a phrase count matching `wc -l data/candidates/symptoms-v2.tsv` minus one, and a file at `.workbench/index/symptoms-v2.faiss`. Most vectors come from the existing cache, so this is fast and mostly free.

- [ ] **Step 7: Commit**

```bash
git add scripts/vector_index.py scripts/test_vector_index.py pyproject.toml uv.lock
git commit -m "Index the normalised vocabulary with FAISS"
```

---

### Task 4: The query path and the command line

**Files:**
- Create: `scripts/search.py`
- Create: `scripts/test_search.py`

**Interfaces:**
- Consumes: `Record`, `facet_multiplier` (Task 1); the two v2 tables (Task 2); `vector_index.load/search/phrases` (Task 3); `_gemini.ask/embed`.
- Produces: `class Retriever` with `normalise(text) -> list[Record]`, `match(records) -> list[Match]`, `rank(matches, n=10) -> list[Hit]`, and `search(text, n=10) -> list[Hit]`; `Match(symptom_id, record, cosine)`; `Hit(slug, score, evidence)` where `evidence` is `list[tuple[str, float]]` of `(core_phrase, contribution)`.

- [ ] **Step 1: Write the failing test**

Scoring is tested with the network stubbed, because the arithmetic is the part that can be wrong quietly.

```python
#!/usr/bin/env python3
"""Self-check for retrieval scoring. Stubs the model; no network.
Run: uv run python scripts/test_search.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from search import Match, Retriever  # noqa: E402
from symptom_schema import Record  # noqa: E402


def fake() -> Retriever:
    r = Retriever.__new__(Retriever)
    r.phrases = ["blood-stained sputum", "cough", "weight loss"]
    r.links = {                       # condition -> symptom_id -> corpus record
        "lung-cancer": {0: Record(concept="sputum", character="blood-stained"),
                        1: Record(concept="cough", duration="over_8_weeks"),
                        2: Record(concept="weight loss")},
        "common-cold": {1: Record(concept="cough", duration="one_to_7_days")},
    }
    r.idf = {0: 3.0, 1: 1.0, 2: 3.0}  # cough is common, so it says little
    return r


def test_rare_symptom_outweighs_common_one():
    r = fake()
    hits = r.rank([Match(0, Record(concept="sputum", character="blood-stained"), 0.95)])
    assert hits[0].slug == "lung-cancer", hits
    assert hits[0].score > 0


def test_absent_symptom_argues_against():
    r = fake()
    present = r.rank([Match(2, Record(concept="weight loss"), 0.99)])[0].score
    absent = r.rank([Match(2, Record(concept="weight loss", polarity="absent"), 0.99)])
    assert absent[0].score < 0 < present, (absent, present)


def test_duration_mismatch_reduces_but_never_reverses():
    r = fake()
    chronic = Record(concept="cough", duration="over_8_weeks")
    acute = Record(concept="cough", duration="under_1_day")
    agree = r.rank([Match(1, chronic, 0.99)])
    clash = r.rank([Match(1, acute, 0.99)])
    lung_agree = next(h.score for h in agree if h.slug == "lung-cancer")
    lung_clash = next(h.score for h in clash if h.slug == "lung-cancer")
    assert 0 < lung_clash < lung_agree, (lung_clash, lung_agree)


def test_evidence_names_the_phrases():
    r = fake()
    hit = r.rank([Match(0, Record(concept="sputum", character="blood-stained"), 0.95)])[0]
    assert [p for p, _ in hit.evidence] == ["blood-stained sputum"], hit.evidence


for fn in (test_rare_symptom_outweighs_common_one, test_absent_symptom_argues_against,
           test_duration_mismatch_reduces_but_never_reverses, test_evidence_names_the_phrases):
    fn()
    print(f"  ok  {fn.__name__}")
print("search: all checks passed")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run python scripts/test_search.py`
Expected: `ModuleNotFoundError: No module named 'search'`

- [ ] **Step 3: Write the module**

```python
#!/usr/bin/env python3
"""Free text in, ten conditions out, with the evidence for each.

    search.py "dry cough for two months, coughing up blood, losing weight"
    search.py --explain "crushing chest pain spreading to my left arm"

The patient's words go through the same form contract as the corpus. That
symmetry is the mechanism: "bringing up blood" and "you may cough up blood"
both normalise to `blood-stained sputum`, so the cosine between them is about
blood and sputum rather than about who was writing.

Weighting is inverse document frequency, a corpus statistic standing in for a
likelihood ratio. It is not a published figure. There is no prevalence here, so
a rare condition that matches the words outranks a common one that matches
slightly fewer. This retrieves; it does not advise.
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import _gemini as G  # noqa: E402
import vector_index as V  # noqa: E402
from symptom_schema import GEMINI_SCHEMA, Record, facet_multiplier, validate  # noqa: E402

CAND = ROOT / "data" / "candidates"
MATCH = 0.80          # cosine below this is not the same symptom
ABSENT_WEIGHT = 0.7   # a denied symptom argues less than a reported one
LENGTH_ALPHA = 0.25   # fitted in triage_poc.py; see its docstring for the table

PROMPT_VERSION = "1"
PATIENT_RULES = """Rewrite this UK patient's description as symptom records under a
fixed form contract.

- concept: one or two words, the symptom itself, the plain UK term. Singular.
- character: at most ONE word, an adjective. One colour word, no compounds.
- site: one word where one exists, otherwise two. Never "area" or "region".
- ONE concept per record. Split anything bundled.
- Lower case, no second person, no hedges, no cause, no disease name.
- polarity is "absent" when the patient denies the symptom.
- Set a band only when the patient states it; never guess. duration_text is
  their own words for it."""


@dataclass(frozen=True)
class Match:
    symptom_id: int
    record: Record       # the PATIENT's record
    cosine: float


@dataclass(frozen=True)
class Hit:
    slug: str
    score: float
    evidence: list[tuple[str, float]]


class Retriever:
    def __init__(self) -> None:
        self.phrases = V.phrases()
        self.index = V.load()
        self.links: dict[str, dict[int, Record]] = {}
        rows = (CAND / "condition-symptoms-v2.tsv").read_text().splitlines()[1:]
        for ln in rows:
            if not ln:
                continue
            cond, sid, onset, dur, dur_text, sev, prog, pol = ln.split("\t")
            self.links.setdefault(cond, {})[int(sid)] = Record(
                concept="x", onset=onset, duration=dur, duration_text=dur_text,
                severity=sev, progression=prog, polarity=pol)
        n = len(self.links)
        seen: dict[int, int] = {}
        for sids in self.links.values():
            for sid in sids:
                seen[sid] = seen.get(sid, 0) + 1
        # +1 on both sides so a symptom every condition lists scores near zero
        # rather than exactly zero, and one nothing lists cannot divide.
        self.idf = {sid: math.log((n + 1) / (c + 1)) + 1.0 for sid, c in seen.items()}

    def normalise(self, text: str) -> list[Record]:
        res = G.ask(f"{PATIENT_RULES}\n\nVERSION {PROMPT_VERSION}\n\nDescription: {text}",
                    schema=GEMINI_SCHEMA)
        out = []
        for raw in res.get("records", []):
            r = Record(concept=raw.get("concept", "").strip().lower(),
                       character=raw.get("character", "").strip().lower(),
                       site=raw.get("site", "").strip().lower(),
                       onset=raw.get("onset", "unspecified"),
                       duration=raw.get("duration", "unspecified"),
                       duration_text=raw.get("duration_text", "").strip(),
                       severity=raw.get("severity", "unspecified"),
                       progression=raw.get("progression", "unspecified"),
                       polarity=raw.get("polarity", "present"))
            try:
                validate(r)
            except ValueError as e:
                print(f"  dropped {r.concept!r}: {e}", file=sys.stderr)
                continue
            out.append(r)
        return out

    def match(self, records: list[Record], k: int = 5) -> list[Match]:
        if not records:
            return []
        vecs = np.array(G.embed([r.core_phrase for r in records]), dtype="float32")
        out: list[Match] = []
        for rec, hits in zip(records, V.search(self.index, vecs, k)):
            for sid, cos in hits:
                if cos >= MATCH:
                    out.append(Match(sid, rec, cos))
        return out

    def rank(self, matches: list[Match], n: int = 10) -> list[Hit]:
        hits: list[Hit] = []
        for slug, stated in self.links.items():
            total = 0.0
            evidence: list[tuple[str, float]] = []
            for m in matches:
                corpus = stated.get(m.symptom_id)
                if corpus is None:
                    continue
                w = self.idf.get(m.symptom_id, 1.0) * m.cosine
                w *= facet_multiplier(corpus, m.record)
                if m.record.polarity == "absent":
                    w = -ABSENT_WEIGHT * w
                total += w
                evidence.append((self.phrases[m.symptom_id], w))
            if not evidence:
                continue
            # Dividing by the full vector length hands an advantage to whatever
            # has fewest symptoms; a fractional power damps that without
            # swinging the other way. See triage_poc.py for the measured table.
            length = sum(self.idf.get(s, 1.0) for s in stated) or 1.0
            hits.append(Hit(slug, total / length ** LENGTH_ALPHA,
                            sorted(evidence, key=lambda e: -abs(e[1]))))
        hits.sort(key=lambda h: -h.score)
        return hits[:n]

    def search(self, text: str, n: int = 10) -> list[Hit]:
        return self.rank(self.match(self.normalise(text)), n)


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        raise SystemExit('usage: search.py "free text describing the symptoms"')
    explain = "--explain" in sys.argv
    r = Retriever()
    records = r.normalise(args[0])
    print("normalised:")
    for rec in records:
        extra = [f"{k}={v}" for k, v in (("onset", rec.onset), ("duration", rec.duration),
                                         ("polarity", rec.polarity))
                 if v not in ("unspecified", "present")]
        print(f"  {rec.core_phrase}" + (f"  [{', '.join(extra)}]" if extra else ""))

    matches = r.match(records)
    if not matches:
        print("\nnothing in the description matched the symptom vocabulary")
        return
    print("\ntop conditions:")
    for i, hit in enumerate(r.rank(matches), 1):
        print(f"  {i:2d}. {hit.score:+.3f}  {hit.slug}")
        if explain:
            for phrase, w in hit.evidence:
                print(f"          {w:+.3f}  {phrase}")
    print("\nRetrieval only, weighted by corpus statistics rather than published "
          "likelihood ratios, with no prevalence. Not clinical advice.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the test and watch it pass**

Run: `uv run python scripts/test_search.py`
Expected: four `ok` lines, then `search: all checks passed`

- [ ] **Step 5: Run it for real**

Run:

```bash
uv run python scripts/search.py --explain "dry cough for two months, coughing up blood, losing weight without trying"
```

Expected: normalised records including `blood-stained sputum` and `weight loss`, a duration band on the cough, ten conditions with lung cancer high, and a per-row evidence breakdown.

- [ ] **Step 6: Commit**

```bash
git add scripts/search.py scripts/test_search.py
git commit -m "Retrieve conditions from free text through the form contract"
```

---

### Task 5: The evaluation

**Files:**
- Create: `eval/run_retrieval_eval.py`

**Interfaces:**
- Consumes: `Retriever`, `Match` (Task 4); `symptom_schema.Record`; the v1 tables for the baseline row.
- Produces: `--held-out [n]`, `--paraphrase [n]` and `--dense [n]` on the command line, printing the rows of the table in §6 of the spec.

Two measurements. The held-out run seeds a condition on two of its own symptoms and asks where it comes back, which is the same design already in `triage_poc.py --eval`, so the baseline row is comparable. The paraphrase run is the one that tests the schema's symmetry claim directly.

- [ ] **Step 1: Write the script**

```python
#!/usr/bin/env python3
"""Does the form contract retrieve better than the string bank it replaces?

    run_retrieval_eval.py --held-out 150    seed a condition on its own symptoms
    run_retrieval_eval.py --paraphrase 200  rewrite a symptom as a patient would

Held-out seeds on the two COMMONEST symptoms, not the rarest. Seeding on the
rarest flatters the score: a symptom two conditions share nearly names the
answer. The commonest is how a patient actually opens.
"""
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import _gemini as G  # noqa: E402
from search import Match, Retriever  # noqa: E402
from symptom_schema import GEMINI_SCHEMA, Record  # noqa: E402

BANNER = """
{bar}
!  Corpus, paraphrases and extraction all come from one scrape and one model.
!  These are retrieval and internal-consistency figures. They are NOT evidence
!  that the knowledge base is clinically correct.
{bar}"""


def held_out(r: Retriever, n: int) -> None:
    random.seed(0)
    pool = [c for c, s in r.links.items() if len(s) >= 3]
    picks = random.sample(pool, min(n, len(pool)))
    top1 = top5 = top10 = 0
    for k, slug in enumerate(picks, 1):
        # commonest first: lowest idf
        sids = sorted(r.links[slug], key=lambda s: r.idf.get(s, 1.0))[:2]
        matches = [Match(s, Record(concept="x"), 1.0) for s in sids]
        order = [h.slug for h in r.rank(matches, n=10)]
        pos = order.index(slug) + 1 if slug in order else None
        top1 += pos == 1
        top5 += bool(pos and pos <= 5)
        top10 += bool(pos)
        print(f"  {k}/{len(picks)} {slug:38s} rank {pos or '>10'}", flush=True)
    t = len(picks)
    print(f"\nheld-out, {t} conditions: top-1 {top1/t:.0%}  "
          f"top-5 {top5/t:.0%}  top-10 {top10/t:.0%}")
    print(BANNER.format(bar="!" * 72))


PARA_PROMPT = ("Rewrite this symptom the way a UK patient would describe it to a "
               "receptionist. One sentence, their words, no medical terms.\n\nSymptom: ")


def paraphrase(r: Retriever, n: int) -> None:
    random.seed(0)
    picks = random.sample(range(len(r.phrases)), min(n, len(r.phrases)))
    hit = 0
    for k, sid in enumerate(picks, 1):
        said = G.ask(PARA_PROMPT + r.phrases[sid]).strip()
        got = {m.symptom_id for m in r.match(r.normalise(said))}
        ok = sid in got
        hit += ok
        print(f"  {k}/{len(picks)} {'ok  ' if ok else 'MISS'} {r.phrases[sid]:34s} <- {said[:60]}",
              flush=True)
    print(f"\nparaphrase recovery: {hit/len(picks):.0%} of {len(picks)}")
    print(BANNER.format(bar="!" * 72))


def main() -> None:
    a = sys.argv
    r = Retriever()
    if "--held-out" in a:
        held_out(r, int(a[a.index("--held-out") + 1]))
    elif "--paraphrase" in a:
        paraphrase(r, int(a[a.index("--paraphrase") + 1]))
    else:
        raise SystemExit("give --held-out N or --paraphrase N")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the held-out evaluation**

Run: `uv run python eval/run_retrieval_eval.py --held-out 150`
Expected: three percentages. The baseline to beat is the existing bank's 75 / 85 / 85, printed in the docstring of `scripts/triage_poc.py`.

- [ ] **Step 3: Run the paraphrase evaluation**

Run: `uv run python eval/run_retrieval_eval.py --paraphrase 200`
Expected: one percentage, plus a visible list of misses. Read ten misses before believing the number; a miss caused by the paraphrase being wrong is not a retrieval failure.

- [ ] **Step 4: Build the dense-vector control**

The spec's fourth table row. One vector per condition instead of one per
symptom, so there is no per-row evidence and no inverse document frequency.
It is a control that says whether the two-stage design earns itself, not a
candidate. Append to `eval/run_retrieval_eval.py`:

```python
def dense(r: Retriever, n: int) -> None:
    """One vector per condition, from its joined symptom profile."""
    import numpy as np

    import vector_index as V

    slugs = sorted(r.links)
    profiles = [", ".join(r.phrases[s] for s in sorted(r.links[slug])) for slug in slugs]
    index = V.from_vectors(np.array(G.embed(profiles, progress=True), dtype="float32"))

    random.seed(0)                      # same seed, same picks as held_out
    pool = [c for c, s in r.links.items() if len(s) >= 3]
    picks = random.sample(pool, min(n, len(pool)))
    top1 = top5 = top10 = 0
    for k, slug in enumerate(picks, 1):
        sids = sorted(r.links[slug], key=lambda s: r.idf.get(s, 1.0))[:2]
        seed = ", ".join(r.phrases[s] for s in sids)
        vec = np.array(G.embed([seed]), dtype="float32")
        order = [slugs[i] for i, _ in V.search(index, vec, k=10)[0]]
        pos = order.index(slug) + 1 if slug in order else None
        top1 += pos == 1
        top5 += bool(pos and pos <= 5)
        top10 += bool(pos)
        print(f"  {k}/{len(picks)} {slug:38s} rank {pos or '>10'}", flush=True)
    t = len(picks)
    print(f"\ndense control, {t} conditions: top-1 {top1/t:.0%}  "
          f"top-5 {top5/t:.0%}  top-10 {top10/t:.0%}")
    print(BANNER.format(bar="!" * 72))
```

And add to `main()`, before the final `raise SystemExit`:

```python
    elif "--dense" in a:
        dense(r, int(a[a.index("--dense") + 1]))
```

Run: `uv run python eval/run_retrieval_eval.py --dense 150`
Expected: three percentages for the control row. Embedding 500 profiles is one
batch and is cached afterwards.

- [ ] **Step 5: Record all the numbers in the spec**

Fill the blank cells in the table in §6 of `docs/phase-1-rag-retrieval-design.md` for the rows "Pass 1, restructured facets" and "Condition-profile dense vectors", and add a line under the table giving the paraphrase-recovery figure.

- [ ] **Step 6: Commit**

```bash
git add eval/run_retrieval_eval.py docs/phase-1-rag-retrieval-design.md
git commit -m "Measure retrieval against the string bank it replaces"
```

---

### Task 6: Normalise from raw prose

**Files:**
- Modify: `scripts/normalise_v2.py` (add `from_raw()` and the `--from-raw` branch)
- Modify: `data/candidates/symptoms-v2.tsv`, `data/candidates/condition-symptoms-v2.tsv` (rebuilt)

**Interfaces:**
- Consumes: `.workbench/nhs/conditions/*.txt` (459 files, one phrase per line), `cluster()` from `scripts/normalise_symptoms.py`.
- Produces: `from_raw(limit: int | None = None) -> list[tuple[str, Record]]`, same shape as `from_bank()`, so `write_tables` is unchanged.

Pass 1 could not recover a facet the canonical string never carried. Pass 2 sees the sentence, so "a cough lasting more than 3 weeks" yields a duration band. Core phrases are then clustered at the existing 0.88 threshold so that near-identical phrasings collapse to one vocabulary entry.

- [ ] **Step 1: Add the function**

```python
def from_raw(limit: int | None = None) -> list[tuple[str, Record]]:
    """Pass 2. One call per condition, over the scraped prose."""
    raw_dir = ROOT / ".workbench" / "nhs" / "conditions"
    files = sorted(raw_dir.glob("*.txt"))[:limit]
    if not files:
        raise SystemExit(f"no scraped prose in {raw_dir}; run harvest_symptoms.py first")

    out: list[tuple[str, Record]] = []
    for k, path in enumerate(files, 1):
        lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
        if not lines:
            continue
        payload = (f"These lines are the symptom section of the NHS page for "
                   f"'{path.stem}'.\n\n" + "\n".join(f"- {ln}" for ln in lines))
        for raw in _flash(payload):
            rec = _record(raw)
            if rec is not None:
                out.append((path.stem, rec))
        print(f"  {k}/{len(files)} {path.stem}", flush=True)
    return collapse(out)


def collapse(links: list[tuple[str, Record]], thresh: float = 0.88
             ) -> list[tuple[str, Record]]:
    """Merge near-identical core phrases onto one wording.

    The same threshold normalise_symptoms.py uses: 0.92 on paraphrases, 0.71 on
    unrelated symptoms, so 0.88 sits between.
    """
    import numpy as np
    from normalise_symptoms import cluster

    phrases = sorted({r.core_phrase for _, r in links})
    vecs = np.array(G.embed(phrases, progress=True), dtype="float32")
    canonical: dict[str, str] = {}
    for group in cluster(phrases, vecs, thresh):
        head = phrases[group[0]]
        for i in group:
            canonical[phrases[i]] = head

    # The slots of the head record, kept whole. Splitting a core phrase back
    # into character/concept/site is lossy -- "chest pain" and "crushing pain"
    # are both two words and only one of them has a character.
    slots: dict[str, Record] = {}
    for _, r in links:
        slots.setdefault(r.core_phrase, r)

    merged = []
    for cond, r in links:
        head = slots[canonical[r.core_phrase]]
        merged.append((cond, Record(concept=head.concept, character=head.character,
                                    site=head.site, onset=r.onset, duration=r.duration,
                                    duration_text=r.duration_text, severity=r.severity,
                                    progression=r.progression, polarity=r.polarity)))
    return merged
```

And in `main()`, replace the final `raise SystemExit(...)` with:

```python
    if "--from-raw" in sys.argv:
        limit = None
        if "--limit" in sys.argv:
            limit = int(sys.argv[sys.argv.index("--limit") + 1])
        write_tables(from_raw(limit))
        return
    raise SystemExit("give --from-bank or --from-raw")
```

- [ ] **Step 2: Smoke-test on twenty conditions**

Run: `uv run python scripts/normalise_v2.py --from-raw --limit 20`
Expected: twenty progress lines, then a symptom and link count. Inspect five rows of `condition-symptoms-v2.tsv` and confirm at least one carries a real duration band with matching `duration_text`.

- [ ] **Step 3: Run the full pass**

Run: `uv run python scripts/normalise_v2.py --from-raw`
Expected: 459 progress lines. This overwrites both v2 tables, so the index must be rebuilt next.

- [ ] **Step 4: Rebuild the index and re-run both evaluations**

Run:

```bash
uv run python scripts/vector_index.py --build
uv run python eval/run_retrieval_eval.py --held-out 150
uv run python eval/run_retrieval_eval.py --paraphrase 200
```

Expected: two more sets of figures, for the row "Pass 2, normalised from raw".

- [ ] **Step 5: Record the numbers and decide**

Fill the pass-2 row in §6 of the spec. If pass 2 does not beat pass 1, say so in the spec under §9 open question 2 and keep pass 1's tables — the comparison is why both were built.

- [ ] **Step 6: Commit**

```bash
git add scripts/normalise_v2.py data/candidates/symptoms-v2.tsv data/candidates/condition-symptoms-v2.tsv docs/phase-1-rag-retrieval-design.md
git commit -m "Normalise from the scraped prose, where the facets still are"
```

---

### Task 7: The notebook cell and the transcript

**Files:**
- Modify: `notebooks/dataset_script.py` (add a section after "Search it")
- Create: `eval/transcript.md`

**Interfaces:**
- Consumes: `Retriever` (Task 4).
- Produces: nothing other tasks depend on.

- [ ] **Step 1: Add the notebook section**

Append to `notebooks/dataset_script.py`:

```python
# ## Search it, through the form contract
#
# The same free text, but the words are normalised into structured records
# first and matched against a FAISS index of the normalised vocabulary. The
# `normalised` column is what the model made of the description; it is the
# part to read sceptically.

# %%

from search import Retriever

r = Retriever()

def search_v2(text, n=10):
    records = r.normalise(text)
    print('normalised:', ' | '.join(x.core_phrase for x in records) or 'nothing')
    hits = r.rank(r.match(records), n=n)
    return pd.DataFrame({
        'condition': [h.slug for h in hits],
        'score': [h.score for h in hits],
        'because': [', '.join(p for p, _ in h.evidence[:3]) for h in hits],
    })

search_v2('dry cough for two months, coughing up blood, losing weight without trying')

# %%

search_v2('sudden crushing chest pain spreading to my left arm, sweating, feeling sick')
```

- [ ] **Step 2: Run the notebook script end to end**

Run: `uv run python notebooks/dataset_script.py`
Expected: it completes without error and the two searches print a normalised line and ten rows each.

- [ ] **Step 3: Write the transcript**

Run `scripts/search.py --explain` on six hand-written descriptions covering: a chronic cough with haemoptysis, an acute chest pain, a thunderclap headache, a vague fatigue presentation, a description containing a denial ("no fever"), and one that should fail — words the vocabulary cannot match. Paste each command and its full output into `eval/transcript.md`, with a sentence per case saying what to notice, including where it is wrong.

Open the file with the same warning the evaluations print: one scrape, one model, no prevalence, retrieval rather than advice.

- [ ] **Step 4: Commit**

```bash
git add notebooks/dataset_script.py eval/transcript.md
git commit -m "Show the retrieval path in the notebook and a worked transcript"
```

---

## Done when

- `uv run python scripts/test_symptom_schema.py`, `scripts/test_vector_index.py` and `scripts/test_search.py` all pass.
- `docs/symptom-schema.md` exists and a person can follow it without reading any code.
- §6 of the spec has no blank cells.
- `eval/transcript.md` shows six cases, including one failure.
