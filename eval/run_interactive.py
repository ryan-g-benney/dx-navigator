#!/usr/bin/env python3
"""Interactive evaluation: drive a full interrogation per vignette.

The simulated patient answers from the vignette and says `unknown` to anything
the vignette does not cover -- which is realistic, and exercises the no-op path.
Reports the question-count and burden metrics that batch scoring cannot measure.
"""
import statistics
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "engine"))

from dx_engine import session as S  # noqa: E402
from dx_engine.kb import load  # noqa: E402

kb = load(ROOT / "data")
vignettes = yaml.safe_load((ROOT / "eval" / "vignettes.yaml").read_text())["vignettes"]

counts: list[int] = []
burdens: list[int] = []
top1 = top3 = n = 0
rf_hit = rf_n = 0
rows: list[str] = []
rf_misses: list[str] = []

for v in vignettes:
    st = S.start(v["complaint"])
    while True:
        view = S.view(kb, st)
        if view.stop is not S.Stop.ONGOING:
            break
        st = S.step(kb, st, view.question, v["answers"].get(view.question, "unknown"))
    view = S.view(kb, st)
    slugs = [r.slug for r in view.ranked]
    counts.append(len(st.asked))
    burdens.append(view.burden)

    if v.get("expect_insufficient"):
        ok = view.stop is S.Stop.INSUFFICIENT
        rows.append(f"  {'PASS' if ok else 'FAIL':4s}  {v['id']:24s} "
                    f"q={len(st.asked):<2} stop={view.stop.value}")
        continue

    n += 1
    truth = v["truth"]
    top1 += slugs[:1] == [truth]
    hit3 = truth in slugs[:3]
    top3 += hit3
    if kb.conditions[truth].urgency.value == "emergency":
        rf_n += 1
        caught = hit3 or view.stop is S.Stop.EMERGENCY
        rf_hit += caught
        if not caught:
            rf_misses.append(f"{v['id']}: {truth} neither ranked nor escalated")
    mark = "1" if slugs[:1] == [truth] else ("3" if hit3 else "-")
    rows.append(f"  [{mark}]   {v['id']:24s} q={len(st.asked):<2} b={view.burden:<2} "
                f"{view.stop.value:26s} {slugs[0]}")

print("\n".join(rows))
print("\n" + "!" * 72)
print("!  Vignettes and condition features share an author. These measure")
print("!  INTERNAL CONSISTENCY, not clinical accuracy. See eval/run_eval.py.")
print("!" * 72)
srt = sorted(counts)
p90 = srt[min(len(srt) - 1, int(round(0.9 * (len(srt) - 1))))]
print(f"\nkb {kb.version_hash}   {n} scored vignettes")
print(f"  top-1 accuracy      {top1/n:.2f}")
print(f"  top-3 accuracy      {top3/n:.2f}   target >= 0.85")
print(f"  median questions    {statistics.median(counts):.0f}      target <= 6")
print(f"  p90 questions       {p90}      target <= 10")
print(f"  mean burden         {statistics.mean(burdens):.1f}    (watched for drift)")
print(f"  red-flag recall     {rf_hit/rf_n:.2f}   target 1.00, hard gate ({rf_n} emergency)")
for m in rf_misses:
    print(f"  RED-FLAG MISS  {m}", file=sys.stderr)
raise SystemExit(1 if rf_n and rf_hit < rf_n else 0)
