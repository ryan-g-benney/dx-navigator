#!/usr/bin/env python3
"""Look up SNOMED CT concept ids and cross-check ICD-10, without any API key.

Sources, both keyless:
  SNOMED  EBI OLS4 (SNOMED CT International Edition)  https://www.ebi.ac.uk/ols4
  ICD-10  NLM Clinical Tables (ICD-10-CM)             https://clinicaltables.nlm.nih.gov

CAVEATS, both material:
  - OLS4 serves the INTERNATIONAL edition. The UK Edition is what a UK product
    needs, and it requires an NHS TRUD account. Codes written here are marked
    for TRUD verification, not treated as settled.
  - ICD-10 verification is NOT attempted here, and the NLM route was removed
    after being tried. NLM serves ICD-10-CM, the US Clinical Modification,
    which demands more digits than WHO ICD-10 (our I26.9 is CM's I26.99). It
    reported 17 of 43 codes "not found" when the codes were fine and the
    classification was simply the wrong one. A check that produces false alarms
    is worse than no check. Verifying ICD-10 needs a WHO or UK source: the
    ICD-11 API (free, needs registration) or NHS TRUD.

Writes candidates to .workbench/codes.md for review. Only exact label matches
are auto-promoted into data/; everything else is listed for a human.
"""
import json
import re
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "engine"))
from dx_engine.kb import load  # noqa: E402

UA = "dx-navigator-research/0.1"


def get(url: str) -> dict | list | None:
    r = subprocess.run(["curl", "-sS", "-m", "40", "-A", UA, "-H", "Accept: application/json", url],
                       capture_output=True, text=True, check=False)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def snomed(name: str) -> list[tuple[str, str]]:
    """Disorder concepts only.

    An unfiltered search returns procedures and observables -- "Aortic
    dissection protocol MRI", "Lung cancer screening declined" -- which look
    plausible in a list and are completely wrong. SNOMED fully specified names
    carry a semantic tag, so require "(disorder)".
    """
    q = urllib.parse.quote(name)
    d = get(f"https://www.ebi.ac.uk/ols4/api/search?q={q}&ontology=snomed&rows=25")
    if not d:
        return []
    hits = [(x.get("short_form", "").replace("SNOMED_", ""), x.get("label", ""))
            for x in d.get("response", {}).get("docs", [])]
    return hits


def icd10cm_by_code(code: str) -> list[tuple[str, str]]:
    """Look the CODE up, not the name.

    Searching CM by condition name and asking whether our code appeared in the
    top five proves nothing -- it produced 20 false alarms. Looking the code up
    tells us whether it exists and what it means.
    """
    d = get("https://clinicaltables.nlm.nih.gov/api/icd10cm/v3/search"
            f"?sf=code&terms={urllib.parse.quote(code)}&maxList=3")
    return [(c, n) for c, n in d[3]] if isinstance(d, list) and len(d) > 3 else []


def norm(s: str) -> str:
    s = re.sub(r"\s*\(.*?\)\s*", " ", s)          # drop SNOMED semantic tags
    return re.sub(r"[^a-z0-9 ]", " ", s.lower()).split() and " ".join(
        re.sub(r"[^a-z0-9 ]", " ", s.lower()).split()) or ""


kb = load(ROOT / "data")
rows, auto = [], {}
for slug, cond in sorted(kb.conditions.items()):
    sn = snomed(cond.name)
    exact = [(c, lbl) for c, lbl in sn if norm(lbl) == norm(cond.name)]
    # No fallback to the top hit. An unfiltered SNOMED search returns
    # procedures and observables -- "Aortic dissection protocol MRI", "Lung
    # cancer screening declined" -- which look plausible in a list and are
    # completely wrong. Exact label match or nothing.
    chosen = exact[0] if exact else None
    cm = []  # see module docstring: ICD-10-CM cannot verify WHO/UK ICD-10
    if exact:
        auto[slug] = chosen[0]
    rows.append(
        f"## {slug}  ({cond.name})\n"
        f"  current icd10 : {cond.codes.icd10}   (UNVERIFIED -- needs a WHO/UK source)\n"
        f"  snomed pick   : {chosen[0] if chosen else '-'}  {chosen[1] if chosen else ''}"
        f"{'   [EXACT]' if exact else '   [REVIEW - label differs]'}\n"
        f"  other snomed  : " + "; ".join(f"{c} {l}" for c, l in sn[1:4]) + "\n"

    )
    time.sleep(0.3)

(ROOT / ".workbench").mkdir(exist_ok=True)
(ROOT / ".workbench" / "codes.md").write_text(
    "# Code lookup candidates\n\nSNOMED = OLS4 International Edition, pending TRUD (UK Edition).\n"
    "ICD-10-CM = US modification, sanity check only.\n\n" + "\n".join(rows))
(ROOT / ".workbench" / "snomed_auto.json").write_text(json.dumps(auto, indent=2, sort_keys=True))
print(f"{len(auto)}/{len(kb.conditions)} exact label matches auto-promotable")
print(f"{len(kb.conditions) - len(auto)} need review -> .workbench/codes.md")
