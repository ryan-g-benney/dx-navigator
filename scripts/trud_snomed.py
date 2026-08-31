#!/usr/bin/env python3
"""Track A: pull the SNOMED is-a poset from TRUD and check our hierarchy against it.

docs/phase-0-acquisition-plan.md §3. SNOMED CT is already a classified poset;
we select a subposet from it rather than deriving a hierarchy of our own.

Licence: the release archive lands in .workbench/ (gitignored) and stays there.
Only concept ids -- which we already store -- ever reach data/.

    trud_snomed.py releases [ITEM]   list what this key can see
    trud_snomed.py fetch [ITEM]      download the latest release archive
    trud_snomed.py check             compare data/categories.yaml against SNOMED
    trud_snomed.py icd10             check our ICD-10 codes against SNOMED's map

The relationship file is read straight out of the zip; unpacking a 1 GB release
to disk twice buys nothing.
"""
from __future__ import annotations

import csv
import io
import json
import os
import subprocess
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WB = ROOT / ".workbench" / "trud"
API = "https://isd.digital.nhs.uk/trud/api/v1/keys"
IS_A = "116680003"
FSN = "900000000000003001"  # fully specified name, one per active concept
DEFAULT_ITEM = "101"  # SNOMED CT UK Clinical Edition, RF2 snapshot

sys.path.insert(0, str(ROOT / "packages" / "engine"))
from dx_engine.kb import load  # noqa: E402


def key() -> str:
    k = os.environ.get("TRUD_API_KEY")
    if not k:
        for line in (ROOT / ".env").read_text().splitlines():
            if line.startswith("TRUD_API_KEY="):
                k = line.split("=", 1)[1].strip()
    if not k:
        sys.exit("no TRUD_API_KEY in environment or .env")
    return k


def api(path: str) -> dict:
    out = subprocess.run(["curl", "-sS", "-m", "60", f"{API}/{key()}/{path}"],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def releases(item: str) -> list[dict]:
    body = api(f"items/{item}/releases?latest")
    if body.get("httpStatus") == 404:
        sys.exit(f"item {item}: no releases visible to this key.\n"
                 "The key is valid but the account is not subscribed to this item.\n"
                 "Subscribe at https://isd.digital.nhs.uk/trud/users/authenticated/"
                 f"filters/0/categories/26/items/{item}/releases -- it needs three licences\n"
                 "accepted, which is a decision for the account holder, not this script.")
    return body["releases"]


def fetch(item: str) -> Path:
    rel = releases(item)[0]
    WB.mkdir(parents=True, exist_ok=True)
    dest = WB / rel["archiveFileName"]
    if dest.exists() and dest.stat().st_size == rel["archiveFileSizeBytes"]:
        print(f"cached {dest.name}")
        return dest
    mb = rel["archiveFileSizeBytes"] / 1e6
    print(f"downloading {rel['name']} -- {dest.name}, {mb:.0f} MB")
    subprocess.run(["curl", "-sSL", "-m", "3600", "-o", str(dest), rel["archiveFileUrl"]], check=True)
    return dest


def is_a_edges(archive: Path) -> dict[str, set[str]]:
    """child -> set of parents, from the active is-a rows of the Relationship snapshot."""
    parents: dict[str, set[str]] = defaultdict(set)
    with zipfile.ZipFile(archive) as z:
        # The release bundles several editions, each naming its own file:
        # sct2_Relationship_Snapshot_INT (International) but
        # sct2_Relationship_UKCLSnapshot (UK Clinical). Match all of them, take
        # Snapshot only (Full and Delta would double-count), take inferred
        # rather than Stated (the classifier's output is the poset we want),
        # and skip the concrete-value file, which holds numbers not concepts.
        names = [n for n in z.namelist()
                 if "/Snapshot/" in n and n.endswith(".txt")
                 and "sct2_Relationship_" in n.rsplit("/", 1)[-1]
                 and "ConcreteValues" not in n]
        if not names:
            sys.exit(f"no sct2_Relationship_Snapshot in {archive.name}")
        for name in names:
            with z.open(name) as fh:
                rows = csv.DictReader(io.TextIOWrapper(fh, "utf-8"), delimiter="\t",
                                          quoting=csv.QUOTE_NONE)
                for r in rows:
                    if r["active"] == "1" and r["typeId"] == IS_A:
                        parents[r["sourceId"]].add(r["destinationId"])
    return parents


def labels(archive: Path, wanted: set[str]) -> dict[str, str]:
    """concept id -> fully specified name, for the ids we are about to print.

    RF2 is tab-delimited with no quoting, so a double quote inside a term is
    literal text. Without QUOTE_NONE the reader swallows the rest of the file.
    """
    out: dict[str, str] = {}
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            if "sct2_Description_Snapshot" not in name or not name.endswith(".txt"):
                continue
            with z.open(name) as fh:
                for r in csv.DictReader(io.TextIOWrapper(fh, "utf-8"), delimiter="\t",
                                          quoting=csv.QUOTE_NONE):
                    if (r["active"] == "1" and r["typeId"] == FSN
                            and r["conceptId"] in wanted):
                        out.setdefault(r["conceptId"], r["term"])
    return out


def ancestors(parents: dict[str, set[str]], start: str) -> set[str]:
    seen: set[str] = set()
    stack = list(parents.get(start, ()))
    while stack:
        c = stack.pop()
        if c not in seen:
            seen.add(c)
            stack.extend(parents.get(c, ()))
    return seen


def assert_acyclic(parents: dict[str, set[str]]) -> None:
    """Iterative three-colour DFS. The release should be acyclic; the validator
    requires our DAG to be, so verify rather than assume."""
    WHITE, GREY, BLACK = 0, 1, 2
    colour: dict[str, int] = {}
    for root in parents:
        if colour.get(root, WHITE) != WHITE:
            continue
        stack = [(root, iter(parents.get(root, ())))]
        colour[root] = GREY
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                colour[node] = BLACK
                stack.pop()
            elif colour.get(nxt, WHITE) == GREY:
                sys.exit(f"is-a graph has a cycle through {nxt}")
            elif colour.get(nxt, WHITE) == WHITE:
                colour[nxt] = GREY
                stack.append((nxt, iter(parents.get(nxt, ()))))


def check(archive: Path) -> None:
    kb = load(ROOT / "data")
    coded = {s: c.codes.snomed for s, c in kb.conditions.items() if c.codes.snomed}
    print(f"{len(coded)}/{len(kb.conditions)} conditions carry a SNOMED code")

    parents = is_a_edges(archive)
    print(f"{sum(len(v) for v in parents.values())} active is-a edges "
          f"over {len(parents)} concepts")
    assert_acyclic(parents)
    print("acyclic: ok")

    anc = {slug: ancestors(parents, sct) for slug, sct in coded.items()}
    rootless = [s for s, a in anc.items() if not a]
    if rootless:
        print(f"NO IS-A ANCESTORS (absent, or an inactive concept): "
              f"{', '.join(sorted(rootless))}")

    # Subsumption inside our own leaf set. Any hit is a KB smell: two conditions
    # where one is an ancestor of the other are not siblings in a pool.
    rev = {sct: slug for slug, sct in coded.items()}
    print("\n== SUBSUMPTION AMONG OUR CONDITIONS ==")
    hits = [(rev[a], slug) for slug, a_set in anc.items() for a in a_set & set(rev)]
    for parent, child in sorted(hits):
        print(f"  {parent} subsumes {child}")
    print("  none" if not hits else "")

    # Candidate categories: SNOMED concepts that sit above two or more of ours.
    # These are what data/categories.yaml is hand-writing; this is the check.
    shared: dict[str, set[str]] = defaultdict(set)
    for slug, a_set in anc.items():
        for a in a_set:
            shared[a].add(slug)
    ranked = sorted(((len(v), a, v) for a, v in shared.items() if 2 <= len(v) < len(anc)),
                    key=lambda t: (-t[0], t[1]))
    top = ranked[:30]
    name = labels(archive, {a for _, a, _ in top})
    print("== SHARED ANCESTORS COVERING 2+ CONDITIONS (widest 30) ==")
    for n, a, members in top:
        print(f"  {n:>2}  {name.get(a, a)}")
        print(f"      {', '.join(sorted(members))}")
    print(f"\n{len(ranked)} shared ancestors total; hand-written categories: "
          f"{len(kb.categories)}")


def icd10(archive: Path) -> None:
    """Compare each condition's ICD-10 code against the SNOMED to ICD-10 map.

    The map is the licensed cross-check the keyless route could not do: it
    catches ICD-10-CM codes that do not exist in WHO ICD-10, and codes less
    specific than the condition they sit on.
    """
    kb = load(ROOT / "data")
    coded = {s: c for s, c in kb.conditions.items() if c.codes.snomed and c.codes.icd10}
    want = {c.codes.snomed for c in coded.values()}

    maps: dict[str, set[str]] = defaultdict(set)
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            base = name.rsplit("/", 1)[-1]
            if "/Snapshot/" not in name or not name.endswith(".txt"):
                continue
            if "ExtendedMap" not in base:
                continue
            with z.open(name) as fh:
                rows = csv.DictReader(io.TextIOWrapper(fh, "utf-8"), delimiter="\t",
                                      quoting=csv.QUOTE_NONE)
                for r in rows:
                    if r["active"] == "1" and r["referencedComponentId"] in want:
                        target = (r.get("mapTarget") or "").strip()
                        if target:
                            maps[r["referencedComponentId"]].add(target)

    # The refset lists each target twice, dotted and undotted (H40.2 and H402).
    # Compare without the dot or every second row reads as a divergence.
    flat = lambda code: code.replace(".", "")  # noqa: E731
    agree = divergent = unmapped = 0
    for slug, c in sorted(coded.items()):
        targets = {flat(x) for x in maps.get(c.codes.snomed, set())}
        ours = flat(c.codes.icd10)
        if not targets:
            print(f"  NO MAP    {slug:34s} ours={c.codes.icd10}")
            unmapped += 1
        elif ours in targets:
            agree += 1
        else:
            if any(ours.startswith(x) for x in targets):
                tag = "NARROWER"  # ours has digits WHO ICD-10 does not define
            elif any(x[:3] == ours[:3] for x in targets):
                tag = "NEARBY  "
            else:
                tag = "MISMATCH"
            print(f"  {tag}  {slug:34s} ours={c.codes.icd10:8s} "
                  f"snomed={','.join(sorted(targets))[:56]}")
            divergent += 1
    print(f"\nexact {agree}, divergent {divergent}, unmapped {unmapped}, "
          f"of {len(coded)} conditions with both codes")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "releases"
    item = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_ITEM
    if cmd == "releases":
        for r in releases(item):
            print(f"{r['id']}  {r['releaseDate']}  "
                  f"{r['archiveFileSizeBytes'] / 1e6:>7.0f} MB  {r['name']}")
    elif cmd == "fetch":
        print(fetch(item))
    elif cmd in ("check", "icd10"):
        archives = sorted(WB.glob("*.zip"))
        if not archives:
            sys.exit("no release in .workbench/trud -- run `trud_snomed.py fetch` first")
        (check if cmd == "check" else icd10)(archives[-1])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
