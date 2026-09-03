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
