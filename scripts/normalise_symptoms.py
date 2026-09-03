#!/usr/bin/env python3
"""Collapse the mined symptom phrases into one canonical vocabulary.

The same symptom reaches us in as many wordings as there are pages: "shortness
of breath", "you may feel breathless", "difficulty breathing". Scoring cannot
treat those as one fact while they are three strings, so they are clustered by
embedding cosine and each cluster is given a single canonical name.

Clustering first and naming clusters second is what keeps this affordable: one
flash call per forty clusters rather than one per phrase.

What lands in data/ is the canonical vocabulary and the condition-to-symptom
links -- clinical terms and facts. The NHS wordings stay in .workbench/.

    normalise_symptoms.py                 cluster at the default threshold
    normalise_symptoms.py --thresh 0.90   tighter clusters, more of them
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import _gemini as G  # noqa: E402

RAW = ROOT / ".workbench" / "nhs" / "conditions"
LABELS = ROOT / ".workbench" / "labels"
# Bumped whenever PROMPT changes: a label cached under the old wording would
# silently keep a judgement the new wording would have reversed.
PROMPT_VERSION = "2"
BANK = ROOT / "data" / "candidates" / "symptom-bank.tsv"
LINKS = ROOT / "data" / "candidates" / "condition-symptoms.tsv"

THRESH = 0.88   # 0.92 on paraphrases, 0.71 on unrelated symptoms; 0.88 sits between.
BATCH = 40

SCHEMA = {
    "type": "object",
    "properties": {
        "labels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "canonical": {"type": "string"},
                    "is_symptom": {"type": "boolean"},
                },
                "required": ["id", "canonical", "is_symptom"],
            },
        }
    },
    "required": ["labels"],
}

PROMPT = """You are normalising symptom wording for a UK clinical decision-support tool.

Each group below holds phrases scraped from NHS condition pages that appear to
describe the same symptom. For each group give ONE canonical symptom name.

Rules for the canonical name:
- A short clinical noun phrase, lower case, 1 to 6 words.
- No second person. "you feel sick" -> "nausea". "your skin is itchy" -> "itchy skin".
- Keep a qualifier only when it changes the symptom: "productive cough" and
  "dry cough" stay apart; "a bad cough" is just "cough".
- Use the plain UK term a patient would recognise, not the Latin one.
- Set is_symptom false when the group is not a symptom at all: treatments,
  risk factors, statistics, body sites with no complaint, page furniture.
- Set is_symptom false for a named condition or disease. NHS symptom sections
  carry differential lists -- the appendicitis page names urinary tract
  infection, kidney stones and Crohn's disease inside its symptom section.
  Those are what the illness might be confused with, not what it feels like.
  "kidney stones" is false. "pain in the side that comes in waves" is true.

Groups:
{groups}"""


def load() -> dict[str, list[str]]:
    return {p.stem: [ln for ln in p.read_text().splitlines() if ln]
            for p in sorted(RAW.glob("*.txt"))}


def cluster(phrases: list[str], vecs: np.ndarray, thresh: float) -> list[list[int]]:
    """Greedy single-pass clustering, densest phrase first.

    Seeding on the phrase that appears in most conditions means the common
    symptom names the cluster and the one-off wordings are absorbed into it,
    rather than a rare phrasing becoming the seed everything else misses.
    """
    unit = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
    order = np.argsort(-unit @ unit.T @ np.ones(len(phrases)))  # by summed similarity
    taken = np.zeros(len(phrases), dtype=bool)
    groups: list[list[int]] = []
    for i in order:
        if taken[i]:
            continue
        sims = unit @ unit[i]
        members = np.where((sims >= thresh) & ~taken)[0]
        taken[members] = True
        groups.append([int(i)] + [int(m) for m in members if m != i])
    return groups


def label(groups: list[list[int]], phrases: list[str]) -> dict[int, str | None]:
    """Canonical name per cluster, one flash call per BATCH clusters, cached."""
    LABELS.mkdir(parents=True, exist_ok=True)
    out: dict[int, str | None] = {}
    pending: list[int] = []
    for gi, g in enumerate(groups):
        key = hashlib.sha256(
            (PROMPT_VERSION + "\n" + "\n".join(sorted(phrases[i] for i in g))).encode()
        ).hexdigest()
        p = LABELS / f"{key}.json"
        if p.exists():
            out[gi] = json.loads(p.read_text())["canonical"]
        else:
            pending.append(gi)

    for start in range(0, len(pending), BATCH):
        chunk = pending[start:start + BATCH]
        blocks = []
        for gi in chunk:
            # Six members is enough to show the flash model what the group is.
            members = [phrases[i] for i in groups[gi][:6]]
            blocks.append(f"[{gi}]\n" + "\n".join(f"- {m}" for m in members))
        res = G.ask(PROMPT.format(groups="\n\n".join(blocks)), schema=SCHEMA)
        got = {int(r["id"]): r for r in res.get("labels", [])}
        for gi in chunk:
            r = got.get(gi)
            name = None
            if r and r.get("is_symptom"):
                name = re.sub(r"\s+", " ", r["canonical"].strip().lower()) or None
            out[gi] = name
            key = hashlib.sha256(
                (PROMPT_VERSION + "\n"
                 + "\n".join(sorted(phrases[i] for i in groups[gi]))).encode()).hexdigest()
            (LABELS / f"{key}.json").write_text(json.dumps({"canonical": name}))
        print(f"  labelled {min(start + BATCH, len(pending))}/{len(pending)} clusters",
              flush=True)
    return out


def main() -> None:
    thresh = float(sys.argv[sys.argv.index("--thresh") + 1]) if "--thresh" in sys.argv else THRESH
    by_cond = load()
    if not by_cond:
        raise SystemExit(f"no mined pages in {RAW}; run harvest_symptoms.py first")

    phrases = sorted({p for ps in by_cond.values() for p in ps})
    print(f"{len(by_cond)} conditions, {len(phrases)} unique phrases")

    vecs = np.array(G.embed(phrases, progress=True), dtype=np.float32)
    groups = cluster(phrases, vecs, thresh)
    print(f"{len(groups)} clusters at cosine >= {thresh}")

    names = label(groups, phrases)
    # Several clusters can be given the same canonical name; that is a merge,
    # and merging is the point, so index by name rather than by cluster.
    phrase_name: dict[str, str] = {}
    for gi, g in enumerate(groups):
        if names.get(gi):
            for i in g:
                phrase_name[phrases[i]] = names[gi]

    ids: dict[str, int] = {}
    links: list[tuple[str, int]] = []
    per_symptom: dict[int, set[str]] = {}
    for slug, ps in by_cond.items():
        for p in ps:
            n = phrase_name.get(p)
            if not n:
                continue
            sid = ids.setdefault(n, len(ids))
            per_symptom.setdefault(sid, set()).add(slug)
    for sid, slugs in per_symptom.items():
        links += [(s, sid) for s in sorted(slugs)]

    BANK.write_text("symptom_id\tcanonical\tn_conditions\n" + "".join(
        f"{sid}\t{name}\t{len(per_symptom[sid])}\n"
        for name, sid in sorted(ids.items(), key=lambda kv: kv[1])))
    LINKS.write_text("condition\tsymptom_id\n" + "".join(
        f"{c}\t{s}\n" for c, s in sorted(links)))

    covered = {c for c, _ in links}
    counts = [sum(1 for c, _ in links if c == x) for x in covered]
    print(f"\n{len(ids)} canonical symptoms -> {BANK}")
    print(f"{len(links)} condition-symptom links -> {LINKS}")
    print(f"{len(covered)} conditions covered, median {sorted(counts)[len(counts)//2]} "
          f"symptoms each")


if __name__ == "__main__":
    main()
