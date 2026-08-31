#!/usr/bin/env python3
"""Fetch PubMed Central open-access articles as plain text for quoting.

PMC's open-access subset is CC BY or similar, so unlike the guideline
publishers its wording can be quoted and redistributed with attribution. The
E-utilities API needs no key. Output is a working copy in .workbench/lit/;
verify_quotes.py checks anything that reaches data/ back against these files.

    fetch_pmc.py 8373882 [more ids...]

Article ids are PMC ids without the PMC prefix. Find them with a normal PubMed
search restricted to "open access"[filter].
"""
import re
import subprocess
import sys
import time
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / ".workbench" / "lit"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
UA = "dx-navigator-research/0.1"


def text_of(xml: str, tag: str) -> str:
    m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", xml, re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1))).strip() if m else ""


def fetch(pmcid: str) -> None:
    r = subprocess.run(
        ["curl", "-sSL", "-m", "60", "-A", UA,
         f"{EUTILS}?db=pmc&id={pmcid}&retmode=xml"],
        capture_output=True, text=True, check=True)
    xml = r.stdout
    if "<article" not in xml:
        sys.exit(f"PMC{pmcid}: no article returned")

    licence = text_of(xml, "license")
    if "creativecommons.org" not in xml:
        sys.exit(f"PMC{pmcid}: no Creative Commons licence found -- refusing to "
                 f"cache an article we cannot quote. Licence text: {licence[:120]!r}")

    body = re.sub(r"(?is)<(table-wrap|ref-list)[^>]*>.*?</\1>", " ", xml)
    body = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)).strip()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"pmc{pmcid}.txt"
    path.write_text(
        f"PMCID: PMC{pmcid}\n"
        f"TITLE: {text_of(xml, 'article-title')}\n"
        f"LICENCE: {licence}\n"
        f"CHARS: {len(body)}\n\n{body}\n")
    print(f"PMC{pmcid}  {len(body):>7} chars  -> {path.name}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for i, pid in enumerate(sys.argv[1:]):
        if i:
            time.sleep(1)  # NCBI asks for 3 requests/second at most
        fetch(pid)
