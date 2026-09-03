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

import copy
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

# --from-bank asks the model to echo back the source id per record so a split
# phrase's pieces can be traced to the old symptom_id they replace. The id
# rides as its own schema field rather than a "[3] " prefix on concept, so
# concept stays the plain one-or-two-word phrase validate() expects.
BANK_SCHEMA = copy.deepcopy(GEMINI_SCHEMA)
_BANK_ITEM = BANK_SCHEMA["properties"]["records"]["items"]
_BANK_ITEM["properties"]["id"] = {"type": "integer"}
_BANK_ITEM["required"] = ["id", "concept", "polarity"]


def _flash(payload: str, schema: dict = GEMINI_SCHEMA) -> list[dict]:
    res = G.ask(f"{RULES}\n\nVERSION {PROMPT_VERSION}\n\n{payload}", schema=schema)
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
    no_id = 0
    for start in range(0, len(ids), BATCH):
        chunk = ids[start:start + BATCH]
        payload = "Symptoms:\n" + "\n".join(f"[{i}] {bank[i]}" for i in chunk)
        for raw in _flash(payload, schema=BANK_SCHEMA):
            sid = raw.get("id")
            if not isinstance(sid, int) or sid not in bank:
                no_id += 1
                continue
            rec = _record(raw)
            if rec is None:
                continue
            for cond in old_links.get(sid, []):
                out.append((cond, rec))
        print(f"  {min(start + BATCH, len(ids))}/{len(ids)} symptoms", flush=True)
    if no_id:
        print(f"  {no_id} records came back without a usable id", file=sys.stderr)
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
