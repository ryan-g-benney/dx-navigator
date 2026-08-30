#!/usr/bin/env python3
"""Report what the knowledge base is missing. Informational -- never fails."""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "engine"))
from dx_engine.kb import load  # noqa: E402

kb = load(Path(__file__).resolve().parents[1] / "data")
C = kb.conditions

def pct(n, d): return f"{n}/{d} ({100*n//d if d else 0}%)"

print("== CODING ==")
for field in ("snomed", "icd10", "icd11", "icpc2"):
    filled = sum(1 for c in C.values() if getattr(c.codes, field))
    print(f"  {field:7s} {pct(filled, len(C))}")

print("\n== PRIORS ==")
print(f"  prior set  {pct(sum(1 for c in C.values() if c.prior is not None), len(C))}")

print("\n== PROVENANCE MIX ==")
types = Counter(kb.sources[f.source].type.value for c in C.values() for f in c.features.values())
tot = sum(types.values())
for t, n in types.most_common():
    print(f"  {t:10s} {pct(n, tot)} of feature assertions")

print("\n== FEATURE DEPTH ==")
depths = sorted(((len(c.features), s) for s, c in C.items()))
print(f"  median {depths[len(depths)//2][0]} features/condition")
print("  thinnest:", ", ".join(f"{s} ({n})" for n, s in depths[:4]))

print("\n== RULE COVERAGE ==")
for cs, comp in kb.complaints.items():
    rules = [r for r in kb.rules.values() if cs in r.complaints]
    print(f"  {cs:12s} pool {len(comp.pool):>2}   rules {len(rules):>2}")
covered = {c.var for r in kb.rules.values() for c in [*r.all_of, *r.any_of]}
print(f"  variables referenced by any rule: {len(covered)}/{len(kb.variables)}")

print("\n== SAFETY ==")
for s, c in sorted(C.items()):
    if c.urgency.value in ("emergency", "same_day") and not c.red_flag_features:
        print(f"  no red flags: {s} ({c.urgency.value})")
emitted = {k for r in kb.rules.values() for k in [r.emit.kind.__str__()]}
print(f"  emit kinds in use: {sorted(emitted)}")

print("\n== UNUSED ==")
used_by_cond = {v for c in C.values() for v in c.features}
orphan = sorted(set(kb.variables) - used_by_cond - covered)
print(f"  variables used by nothing: {orphan or 'none'}")

print("\n== MULTI-POOL CONDITIONS ==")
for s in sorted(C):
    n = [cs for cs, comp in kb.complaints.items() if s in comp.pool]
    if len(n) > 1:
        print(f"  {s}: {n}")

print("\n== NOT YET PRESENT ==")
print("  safety-netting text: 0 conditions (Track D, needs NHS API key)")
print(f"  eval vignettes: {len(list((Path('eval')).glob('*')))} files")
print("  demographic modifiers (sex, pregnancy, immunosuppression): no schema field")
