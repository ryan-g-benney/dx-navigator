#!/usr/bin/env python3
"""Mine presentation-to-condition links from the NHS symptom pages.

Every automated route to this mapping had failed. Wikidata is rare-disease
biased, SNOMED's Due to relationships recover 5% of a hand-authored pool, and
the consumer medical sites are blocked. The NHS symptom pages turn out to carry
it in a table: one column describes how the symptom presents, the next names
the possible cause.

Only the cause column is read. The description column is NHS prose and stays
out of the repository, exactly as in audit_nhs_coverage.py. What is stored is a
mapping between a presentation and a condition, plus the SNOMED code the cause
name resolves to -- names and codes, which are facts.

    harvest_causes.py            use cached pages, fetch what is missing
    harvest_causes.py --refetch  ignore the cache
"""
from __future__ import annotations

import csv
import html
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import harvest_conditions as H  # noqa: E402
import trud_snomed as t  # noqa: E402

CACHE = ROOT / ".workbench" / "nhs" / "symptoms"
OUT = ROOT / "data" / "candidates" / "presentation-causes.tsv"
UA = "dx-navigator-research/0.1"

CELL = re.compile(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>")
# Half the pages use a table, half a bulleted list under a "Causes of X"
# heading, and a few use both. Dizziness is one of the both.
HEADING = re.compile(r"(?is)<h[23][^>]*>[^<]*causes?[^<]*</h[23]>")
LIST_ITEM = re.compile(r"(?is)<li[^>]*>(.*?)</li>")
ROW = re.compile(r"(?is)<tr[^>]*>(.*?)</tr>")
TABLE = re.compile(r"(?is)<table[^>]*>(.*?)</table>")
# "Chest infection, pneumonia or pleurisy" is three causes in one cell.
SPLIT = re.compile(r"\s*(?:,| or | and/or )\s*")
# "infections like bronchitis" names bronchitis; "allergies - for example" is a
# fragment with the example in the next split part.
EXAMPLE = re.compile(r"^.*?\b(?:like|such as|including)\s+", re.I)
TRAILING = re.compile(r"\s*[-\u2013\u2014]\s*(for example|such as|eg|e\.g\.).*$", re.I)
NOT_A_CONDITION = {
    "for example", "smoking", "stress", "anxiety or stress", "certain medicines",
    "medicines", "alcohol", "caffeine", "pregnancy", "your period", "periods",
    "getting older", "being overweight", "dehydration",
}


def clean_cause(raw: str) -> str:
    x = TRAILING.sub("", raw).strip(" .\u2013\u2014-")
    x = EXAMPLE.sub("", x).strip()
    return x


def text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def causes(slug: str, refetch: bool) -> list[str] | None:
    """The cause column of the symptom page's table, split into single names."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{slug}.tsv"
    if path.exists() and not refetch:
        return [ln for ln in path.read_text().splitlines() if ln]
    r = subprocess.run(["curl", "-sSL", "-m", "40", "-A", UA, "-w", "\\n%{http_code}",
                        f"https://www.nhs.uk/symptoms/{slug}/"],
                       capture_output=True, text=True, check=False)
    raw, _, code = r.stdout.rpartition("\n")
    time.sleep(1)
    if code.strip() != "200":
        return None
    found: list[str] = []

    # Bulleted causes: from a heading that mentions causes to the next heading.
    for m in HEADING.finditer(raw):
        nxt = re.search(r"(?is)<h[23][^>]*>", raw[m.end():])
        block = raw[m.end(): m.end() + (nxt.start() if nxt else 4000)]
        for item in LIST_ITEM.findall(block):
            for part in SPLIT.split(text(item)):
                part = clean_cause(part)
                if (3 <= len(part) <= 60 and len(part.split()) <= 6
                        and part.lower() not in NOT_A_CONDITION):
                    found.append(part)

    for tbl in TABLE.findall(raw):
        rows = ROW.findall(tbl)
        for row in rows[1:]:                      # first row is the header
            cells = [text(c) for c in CELL.findall(row)]
            if len(cells) < 2:
                continue
            for part in SPLIT.split(cells[-1]):   # cause column is the last one
                part = clean_cause(part)
                # Keep it a name: drop sentence fragments and bare qualifiers.
                if (3 <= len(part) <= 60 and len(part.split()) <= 6
                        and part.lower() not in NOT_A_CONDITION):
                    found.append(part)
    path.write_text("\n".join(found))
    return found


def main() -> None:
    refetch = "--refetch" in sys.argv
    archive = sorted(t.WB.glob("*.zip"))
    if not archive:
        sys.exit("no SNOMED release -- run trud_snomed.py fetch")
    term, _keep, _par = H.snomed_index(archive[-1])

    # The cause names are lay terms and so are the A to Z names, so the harvest
    # already done resolves what SNOMED's own vocabulary does not: hay fever is
    # in the A to Z, not in SNOMED under that phrase.
    az: dict[str, str] = {}
    az_path = ROOT / "data" / "candidates" / "conditions.tsv"
    if az_path.exists():
        for row in csv.DictReader(az_path.open(), delimiter="\t"):
            for v in H.variants(row["name"]):
                az.setdefault(v, row["snomed"])

    syms = H.symptom_slugs(refetch)
    rows, no_table, pages = [], [], 0
    for slug in sorted(syms):
        got = causes(slug, refetch)
        if got is None:
            continue
        pages += 1
        if not got:
            no_table.append(slug)
            continue
        for name in dict.fromkeys(got):
            cid = ""
            for cand in H.variants(name):
                ids = term.get(cand, set())
                if len(ids) == 1:
                    cid = next(iter(ids))
                    break
                if not cid and cand in az:
                    cid = az[cand]
            rows.append((slug, name, cid))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w") as fh:
        fh.write("presentation\tcause_name\tsnomed\n")
        for r in rows:
            fh.write("\t".join(r) + "\n")

    coded = sum(1 for _, _, c in rows if c)
    linked = len({s for s, _, _ in rows})
    print(f"symptom pages fetched      {pages}")
    print(f"pages with a cause table   {pages - len(no_table)}")
    print(f"presentation-cause links   {len(rows)}")
    print(f"  distinct presentations   {linked}")
    print(f"  cause resolved to SNOMED {coded} ({coded / len(rows):.0%})")
    print(f"  distinct causes          {len({n for _, n, _ in rows})}")
    print(f"\nwrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
