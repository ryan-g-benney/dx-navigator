#!/usr/bin/env python3
"""Harvest a candidate condition list and code it against the SNOMED release.

The knowledge base has 43 conditions across three complaints, which is a
prototype. This mines a far larger candidate list so the coverage question can
be answered with data rather than by hand-picking.

The NHS A to Z supplies the names: a curated, UK, primary-care-facing list of
what a patient might present with. Names and codes are facts and may be stored;
no NHS prose is fetched or kept by this script, only the index of links.

SNOMED supplies the code, the body system and, through its map, the ICD-10.

    harvest_conditions.py            harvest, match, write the candidate table
    harvest_conditions.py --refetch  ignore the cached index
"""
from __future__ import annotations

import csv
import html
import io
import re
import subprocess
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import trud_snomed as t  # noqa: E402

INDEX = ROOT / ".workbench" / "nhs" / "_az_index.html"
OUT = ROOT / "data" / "candidates" / "conditions.tsv"
UA = "dx-navigator-research/0.1"
DISEASES: set[str] = set()
FINDING = "404684003"   # Clinical finding, the ancestor everything sits under
DISEASE = "64572001"    # Disease. A finding that is not one is a presentation:
                        # back pain and constipation are what a patient arrives
                        # with, not what they turn out to have. The project has
                        # three complaints and needs more, so the split matters.


def az_slugs(refetch: bool) -> dict[str, str]:
    """slug -> display name, from the NHS A to Z index page."""
    if not INDEX.exists() or refetch:
        INDEX.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(["curl", "-sSL", "-m", "60", "-A", UA,
                            "https://www.nhs.uk/conditions/"],
                           capture_output=True, text=True, check=True)
        INDEX.write_text(r.stdout)
    raw = INDEX.read_text()
    out: dict[str, str] = {}
    for m in re.finditer(r'href="/conditions/([a-z0-9-]+)/"[^>]*>(.*?)</a>', raw, re.S):
        name = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", m.group(2)))).strip()
        if name and len(name) < 90:
            out.setdefault(m.group(1), name)
    return out


# Medical plurals do not follow the English rule: keratoses is keratosis, not
# keratose, and bacilli is bacillus. Order matters, longest suffix first.
PLURAL = [("oses", "osis"), ("ses", "sis"), ("ae", "a"), ("i", "us"),
          ("ies", "y"), ("es", ""), ("s", "")]
QUALIFIER = re.compile(
    r"\s+(in adults?|in children( and young people)?|in babies|in men|in women"
    r"|in pregnancy|in over \d+s|in under \d+s)$")


def variants(display: str) -> list[str]:
    """Normalised forms to try, most faithful first.

    The A to Z is written for patients, so a name may be a cross-reference, a
    lay synonym in brackets, an age qualifier, or a plural. Each is a different
    string from the SNOMED term for the same concept.
    """
    out: list[str] = []

    def add(x: str) -> None:
        x = norm(x)
        if x and x not in out:
            out.append(x)

    # "Arrhythmia, see Heart rhythm problems" -- the target is the real name.
    body = display.split(", see ", 1)[-1] if ", see " in display else display
    add(body)
    if body is not display:
        add(display.split(", see ", 1)[0])
    # "Actinic keratoses (solar keratoses)" -- try the bracketed alternate too.
    for alt in re.findall(r"\(([^)]+)\)", body):
        if len(alt.split()) <= 6 and not alt.isupper():
            add(alt)
    stripped = QUALIFIER.sub("", norm(body))
    add(stripped)
    for base in list(out):
        for suf, rep in PLURAL:
            if base.endswith(suf) and len(base) - len(suf) >= 3:
                add(base[: -len(suf)] + rep)
                break
    return out


def norm(s: str) -> str:
    s = s.lower()
    s = re.sub(r"\s*\([^)]*\)", " ", s)          # drop parenthetical, incl semantic tag
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return " ".join(s.split())


def descendants(kids: dict[str, set[str]], root: str) -> set[str]:
    seen: set[str] = set()
    stack = [root]
    while stack:
        for k in kids.get(stack.pop(), ()):
            if k not in seen:
                seen.add(k)
                stack.append(k)
    return seen


def snomed_index(archive: Path) -> tuple[dict[str, set[str]], set[str], dict[str, set[str]]]:
    """normalised term -> concept ids, the finding descendants, and child->parents."""
    parents = t.is_a_edges(archive)
    kids: dict[str, set[str]] = defaultdict(set)
    for c, ps in parents.items():
        for p in ps:
            kids[p].add(c)
    keep = descendants(kids, FINDING)
    global DISEASES
    DISEASES = descendants(kids, DISEASE)

    term: dict[str, set[str]] = defaultdict(set)
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            base = name.rsplit("/", 1)[-1]
            if "/Snapshot/" not in name or not name.endswith(".txt"):
                continue
            if not base.startswith("sct2_Description_"):
                continue
            with z.open(name) as fh:
                for r in csv.DictReader(io.TextIOWrapper(fh, "utf-8"), delimiter="\t",
                                        quoting=csv.QUOTE_NONE):
                    if r["active"] == "1" and r["conceptId"] in keep:
                        term[norm(r["term"])].add(r["conceptId"])
    return term, keep, parents


def icd10_map(archive: Path, wanted: set[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            base = name.rsplit("/", 1)[-1]
            if "/Snapshot/" in name and name.endswith(".txt") and "ExtendedMap" in base:
                with z.open(name) as fh:
                    for r in csv.DictReader(io.TextIOWrapper(fh, "utf-8"), delimiter="\t",
                                            quoting=csv.QUOTE_NONE):
                        cid = r["referencedComponentId"]
                        tgt = (r.get("mapTarget") or "").strip()
                        if r["active"] == "1" and cid in wanted and tgt and "." in tgt:
                            out.setdefault(cid, tgt)
    return out


# Body systems, coarse on purpose: enough to bucket a candidate, not a
# hierarchy. Ordered, because a concept has many ancestors and the first match
# wins: neoplasm and infection before the organ they sit in, since "lung
# cancer" is more usefully filed under neoplasm than respiratory.
#
# Ids verified against the release rather than recalled. The first pass used
# 80659006 for endocrine, which is actually Disorder of skin, and every skin
# condition landed in the wrong bucket.
SYSTEMS = [
    ("55342001", "neoplasm"),
    ("40733004", "infectious"),
    ("74732009", "mental-health"),
    ("417746004", "traumatic-or-injury"),
    ("50043002", "respiratory"),
    ("49601007", "cardiovascular"),
    ("118940003", "neurological"),
    ("53619000", "digestive"),
    ("42030000", "genitourinary"),
    ("928000", "musculoskeletal"),
    ("362969004", "endocrine"),
    ("41266007", "immune"),
    ("95320005", "skin"),
    ("362966006", "ear"),
    ("128127008", "eye"),
]


def main() -> None:
    archive = sorted(t.WB.glob("*.zip"))
    if not archive:
        sys.exit("no SNOMED release in .workbench/trud -- run trud_snomed.py fetch")
    archive = archive[-1]

    names = az_slugs("--refetch" in sys.argv)
    print(f"NHS A to Z: {len(names)} conditions")

    term, _keep, parents = snomed_index(archive)
    print(f"SNOMED: {len(term)} distinct terms under Clinical finding")

    matched: dict[str, tuple[str, str]] = {}
    ambiguous, unmatched = [], []
    for slug, display in sorted(names.items()):
        hit = None
        for cand in variants(display):
            ids = term.get(cand, set())
            if len(ids) == 1:
                hit = next(iter(ids))
                break
            if ids and hit is None:
                hit = "AMBIG"
        if hit and hit != "AMBIG":
            matched[slug] = (display, hit)
        elif hit == "AMBIG":
            ambiguous.append((slug, display, 0))
        else:
            unmatched.append((slug, display))

    codes = icd10_map(archive, {c for _, c in matched.values()})

    sys_of = {}
    for slug, (_d, cid) in matched.items():
        anc = t.ancestors(parents, cid)
        sys_of[slug] = next((v for k, v in SYSTEMS if k in anc), "unclassified")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w") as fh:
        fh.write("slug\tname\tsnomed\ticd10\tsystem\tkind\n")
        for slug, (display, cid) in sorted(matched.items()):
            kind = "disorder" if cid in DISEASES else "presentation"
            fh.write(f"{slug}\t{display}\t{cid}\t{codes.get(cid, '')}"
                     f"\t{sys_of[slug]}\t{kind}\n")

    print(f"\nmatched   {len(matched)}")
    print(f"ambiguous {len(ambiguous)}  (term maps to more than one concept)")
    print(f"unmatched {len(unmatched)}")
    print(f"with icd10 {sum(1 for _, c in matched.values() if c in codes)}")
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    kinds = defaultdict(int)
    for _d, cid in matched.values():
        kinds["disorder" if cid in DISEASES else "presentation"] += 1
    print(f"  disorders     {kinds['disorder']}")
    print(f"  presentations {kinds['presentation']}  (candidate complaints)")
    print()
    counts = defaultdict(int)
    for v in sys_of.values():
        counts[v] += 1
    for k, n in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {k:22s} {n}")


if __name__ == "__main__":
    main()
