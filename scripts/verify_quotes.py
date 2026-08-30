#!/usr/bin/env python3
"""Check every rule's text_verbatim still appears in its fetched source.

The NICE UK Open Content Licence forbids amending the wording of a published
recommendation. The builder guarantees fidelity at generation time; this checks
it independently, so a later hand-edit is caught rather than shipped.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "engine"))
from dx_engine.kb import load  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
WB = ROOT / ".workbench" / "nice"

corpus = {}
for f in WB.glob("*.txt"):
    corpus[f.stem] = re.sub(r"\s+", " ", f.read_text())

kb = load(ROOT / "data")
if not corpus:
    print("no fetched sources in .workbench/nice -- run scripts/fetch_nice.py first")
    raise SystemExit(1)

bad = 0
for rid, rule in sorted(kb.rules.items()):
    needle = re.sub(r"\s+", " ", rule.emit.text_verbatim).strip()
    hit = next((name for name, text in corpus.items() if needle in text), None)
    if hit:
        print(f"  PASS  {rid:22s} exact match in {hit} ({len(needle)} chars)")
    else:
        print(f"  FAIL  {rid:22s} not found verbatim in any fetched source", file=sys.stderr)
        bad += 1

print(f"\n{len(kb.rules) - bad}/{len(kb.rules)} verbatim quotes verified")
raise SystemExit(1 if bad else 0)
