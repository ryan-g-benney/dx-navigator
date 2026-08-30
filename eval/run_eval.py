#!/usr/bin/env python3
"""Evaluation harness. Reports the baseline before anything is tuned.

Red-flag recall is a gate: an emergency ground truth must either appear in the
top 3 or trigger an emergency rule. Below 1.00 the run fails.
"""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "engine"))

from dx_engine.kb import load  # noqa: E402
from dx_engine.rules import fired  # noqa: E402
from dx_engine.score import rank  # noqa: E402

kb = load(ROOT / "data")
vignettes = yaml.safe_load((ROOT / "eval" / "vignettes.yaml").read_text())["vignettes"]

top1 = top3 = n = 0
adv_top3 = adv_n = 0
rf_hit = rf_n = 0
misses: list[str] = []
rf_misses: list[str] = []

for v in vignettes:
    ranked = rank(kb, v["complaint"], v["answers"], top=5)
    slugs = [r.slug for r in ranked]

    if v.get("expect_insufficient"):
        ok = all(r.insufficient for r in ranked)
        print(f"  {'PASS' if ok else 'FAIL':4s}  {v['id']:24s} insufficient-evidence check")
        if not ok:
            misses.append(f"{v['id']}: expected all insufficient, got {slugs[0]}")
        continue

    n += 1
    truth = v["truth"]
    hit1, hit3 = slugs[:1] == [truth], truth in slugs[:3]
    top1 += hit1
    top3 += hit3
    if v.get("adversarial"):
        adv_n += 1
        adv_top3 += hit3
    if not hit3:
        misses.append(f"{v['id']}: {truth} not in top 3 -> {slugs[:3]}")

    if kb.conditions[truth].urgency.value == "emergency":
        rf_n += 1
        escalated = any(r.emit.urgency.value == "emergency" for r in fired(kb, v["complaint"], v["answers"]))
        caught = hit3 or escalated
        rf_hit += caught
        if not caught:
            rf_misses.append(f"{v['id']}: {truth} neither ranked nor escalated")

    mark = "1" if hit1 else ("3" if hit3 else "-")
    flag = " *" if v.get("adversarial") else ""
    print(f"  [{mark}]   {v['id']:24s} {truth:32s} {slugs[0]}{flag}")

print("\n" + "!" * 72)
print("!  These vignettes and the condition features were authored by the SAME")
print("!  hand. The scores below therefore measure INTERNAL CONSISTENCY, not")
print("!  clinical accuracy -- a vignette drawn from a feature profile will")
print("!  match that profile. They demonstrate the machinery works. They are")
print("!  NOT evidence the knowledge base is clinically correct.")
print("!  Real numbers need vignettes authored independently, ideally by a GP")
print("!  from anonymised cases, against a knowledge base they did not write.")
print("!" * 72)
print(f"\nkb {kb.version_hash}   {n} scored vignettes ({adv_n} adversarial)")
print(f"  top-1 accuracy          {top1/n:.2f}")
print(f"  top-3 accuracy          {top3/n:.2f}   target >= 0.85")
print(f"  top-3, adversarial only {adv_top3/adv_n:.2f}")
print(f"  red-flag recall         {rf_hit/rf_n:.2f}   target 1.00, hard gate  ({rf_n} emergency vignettes)")

for m in misses:
    print(f"  MISS  {m}")
for m in rf_misses:
    print(f"  RED-FLAG MISS  {m}", file=sys.stderr)

if rf_n and rf_hit < rf_n:
    print("\nFAIL: red-flag recall below 1.00", file=sys.stderr)
    raise SystemExit(1)
raise SystemExit(0)
