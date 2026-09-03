#!/usr/bin/env python3
"""Mine the symptom section of every NHS condition page.

The mined condition list carries names and codes but no clinical content, and
presentation-causes gives 518 of 601 conditions exactly one symptom -- a
one-symptom vector cannot be compared against another by cosine, every
"cough" condition lands on the same point. This fills that in from the
"Symptoms of X" section each NHS condition page carries.

Raw NHS prose stays in .workbench/, which is gitignored, exactly as in
audit_nhs_coverage.py and harvest_causes.py. What reaches data/ is the
normalised symptom vocabulary produced by normalise_symptoms.py -- clinical
terms, which are facts, not the page's wording.

    harvest_symptoms.py             use cached pages, fetch what is missing
    harvest_symptoms.py --refetch   ignore the cache
    harvest_symptoms.py --limit 20  first 20 slugs only, for a smoke test
"""
from __future__ import annotations

import html
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".workbench" / "nhs" / "conditions"
CONDITIONS = ROOT / "data" / "candidates" / "conditions.tsv"
UA = "dx-navigator-research/0.1"

# "Symptoms of asthma", "Symptoms and signs of X", "Check if you have X".
# The last is the NHS house style on short pages and is the symptom list.
HEADING = re.compile(
    r"(?is)<h([23])[^>]*>\s*(?:[^<]*\bsymptoms?\b[^<]*|check if (?:you|your child)[^<]*)</h\1>")
# "Symptoms" in a heading does not make the section symptoms. "Other conditions
# with similar symptoms" is a differential list, and taking it made appendicitis
# claim kidney stones and Crohn's as its own. "Symptoms after meningitis" is
# complications, which are what the illness leaves behind, not what it presents
# with. Both have to be excluded by name -- the word alone cannot tell them apart.
NOT_SYMPTOMS = re.compile(
    r"(?i)other condition|similar symptom|\bafter\b|complication|long-?term|"
    r"treat|vaccin|immunis|prevent|diagnos|\bcauses?\b|risk|recover|"
    r"living with|when to|where to|help and support")
NEXT_HEAD = re.compile(r"(?is)<h[23][^>]*>")
LI = re.compile(r"(?is)<li[^>]*>(.*?)</li>")
P = re.compile(r"(?is)<p[^>]*>(.*?)</p>")

# Page furniture that sits inside the section but says nothing clinical.
JUNK = re.compile(
    r"(?i)^(find out|read more|see a gp|call 999|call 111|ask for|go to|more in|"
    r"back to|page last|next review|urgent advice|immediate action|non-urgent|"
    r"information:|important:?$|get help|you can|this page|these are)")
# Prose brings the sentence that introduces the list along with it.
LEAD_IN = re.compile(r"(?i)(symptoms?|signs?)\b.*\b(include|are|can be|may be)\s*:?\s*$")
# Image captions carry the agency's credit line inside the section. They are
# not symptoms and the URL fragment survives sentence splitting on the dot.
CREDIT = re.compile(r"(?i)http|photo library|alamy|getty|science photo|stock photo|"
                    r"shutterstock|\bDR [A-Z]|/ ?SPL\b")


def text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def fetch(url: str) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.read().decode("utf-8", "replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None


# A second NHS template puts the symptoms on their own /symptoms/ page and
# gives it no h2 or h3 heading at all -- the whole page is the section. Lung
# cancer, mesothelioma and covid-19 all use it, so the heading rule alone drops
# them. Page furniture is stripped by tag before the list items are read.
CHROME = re.compile(r"(?is)<(nav|header|footer|script|style|aside)\b.*?</\1>")


def whole_page(raw: str) -> list[str]:
    return [text(x) for x in LI.findall(CHROME.sub(" ", raw))]


def section(raw: str, pre: list[str] | None = None) -> list[str]:
    """Every symptom phrase under a symptoms heading, list items preferred."""
    out: list[str] = list(pre) if pre else []
    for m in HEADING.finditer(raw):
        if NOT_SYMPTOMS.search(text(m.group(0))):
            continue
        rest = raw[m.end():]
        nxt = NEXT_HEAD.search(rest)
        body = rest[: nxt.start()] if nxt else rest[:6000]
        # Both, always. Taking the list alone loses the cardinal symptom
        # whenever a page states it in prose and then bullets the secondary
        # signs -- acute cholecystitis leads with "sudden sharp pain in the
        # upper right side of your tummy" and bullets only fever, nausea and
        # jaundice, so the list on its own describes the wrong illness.
        items = [text(x) for x in LI.findall(body)]
        items += [s.strip() for p in P.findall(body) for s in text(p).split(".")]
        out += items
    seen: set[str] = set()
    keep: list[str] = []
    for x in out:
        # Two words minimum: "and", "or" and stray link text are not symptoms.
        if not (3 < len(x) < 200) or len(x.split()) < 2 or JUNK.match(x):
            continue
        if CREDIT.search(x) or LEAD_IN.search(x):
            continue
        if x.lower() not in seen:
            seen.add(x.lower())
            keep.append(x)
    return keep


def symptoms(slug: str, refetch: bool) -> list[str] | None:
    path = CACHE / f"{slug}.txt"
    if path.exists() and not refetch:
        return [ln for ln in path.read_text().splitlines() if ln]
    found: list[str] = []
    for url in (f"https://www.nhs.uk/conditions/{slug}/",
                f"https://www.nhs.uk/conditions/{slug}/symptoms/"):
        raw = fetch(url)
        time.sleep(0.5)
        if raw:
            found += section(raw)
            # Only for the /symptoms/ page: there the whole page is the section,
            # so falling back to it cannot pull in another topic's list.
            if not found and url.endswith("/symptoms/"):
                found += section(raw, pre=whole_page(raw))
        # The main page usually holds it; only pay for the sub-page when it did not.
        if found:
            break
    if not found:
        return None
    path.write_text("\n".join(dict.fromkeys(found)) + "\n")
    return found


def main() -> None:
    refetch = "--refetch" in sys.argv
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    CACHE.mkdir(parents=True, exist_ok=True)

    rows = [ln.split("\t") for ln in CONDITIONS.read_text().splitlines()[1:] if ln]
    slugs = [r[0] for r in rows][:limit]

    hits = misses = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        for slug, got in zip(slugs, pool.map(lambda s: symptoms(s, refetch), slugs)):
            if got:
                hits += 1
            else:
                misses += 1
                print(f"  MISS {slug}")
    print(f"\n{hits} conditions with symptoms, {misses} without, cached in {CACHE}")


if __name__ == "__main__":
    main()
