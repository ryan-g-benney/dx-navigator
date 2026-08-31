#!/usr/bin/env python3
"""Where the knowledge base cannot tell two conditions apart, and why.

The scorer compares a condition's expected values against the answers given.
Two conditions in the same pool are only separable if they both assert some
variable AND their expected values for it are disjoint. Where that never
happens the ranking between them is decided by nothing, and no amount of
questioning will fix it -- the data is missing, not the algorithm.

Three findings, cheapest first:
  dead variable   every condition asserting it expects the same values
  no separator    a pair sharing variables, none of them disjoint
  no overlap      a pair sharing no variable at all, so never compared
"""
from __future__ import annotations

import itertools
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "engine"))
from dx_engine.kb import load  # noqa: E402


def separators(kb, a: str, b: str) -> tuple[list[str], set[str]]:
    """Variables whose expected values are disjoint, and the shared variables."""
    fa, fb = kb.conditions[a].features, kb.conditions[b].features
    shared = set(fa) & set(fb)
    return [v for v in sorted(shared)
            if not (set(fa[v].expect) & set(fb[v].expect))], shared


def main() -> None:
    kb = load(ROOT / "data")
    worst: list[tuple[int, int, str, str, str]] = []

    for cname, comp in sorted(kb.complaints.items()):
        pool = sorted(comp.pool)
        used: dict[str, int] = defaultdict(int)
        for slug in pool:
            for var in kb.conditions[slug].features:
                used[var] += 1

        dead = []
        for var, n in sorted(used.items()):
            if n < 2:
                continue
            values = {frozenset(kb.conditions[s].features[var].expect)
                      for s in pool if var in kb.conditions[s].features}
            if len(values) == 1:
                dead.append(f"{var} ({n})")

        pairs = list(itertools.combinations(pool, 2))
        no_sep = no_shared = 0
        for a, b in pairs:
            sep, shared = separators(kb, a, b)
            if not shared:
                no_shared += 1
            if not sep:
                no_sep += 1
                worst.append((len(shared), len(sep), cname, a, b))

        cells = sum(len(kb.conditions[s].features) for s in pool)
        density = cells / (len(pool) * len(used))
        print(f"== {cname} ==")
        print(f"  matrix {len(pool)}x{len(used)}, {density:.0%} filled")
        print(f"  pairs {len(pairs)}, no separator {no_sep} "
              f"({no_sep / len(pairs):.0%}), never compared {no_shared}")
        if dead:
            print(f"  dead variables: {', '.join(dead)}")
        print()

    # An inseparable pair that disagrees about urgency is the dangerous kind:
    # the ranking cannot choose, and the two answers imply different actions.
    rank = {"routine": 0, "urgent": 1, "same_day": 2, "emergency": 3}
    unsafe = [(shared, cname, a, b) for shared, _, cname, a, b in worst
              if rank[kb.conditions[a].urgency.value]
              != rank[kb.conditions[b].urgency.value]]

    print("== INSEPARABLE AND DISAGREE ON URGENCY ==")
    for shared, cname, a, b in sorted(unsafe, key=lambda t: (-abs(
            rank[kb.conditions[t[2]].urgency.value]
            - rank[kb.conditions[t[3]].urgency.value]), t[0])):
        ua = kb.conditions[a].urgency.value
        ub = kb.conditions[b].urgency.value
        gap = abs(rank[ua] - rank[ub])
        print(f"   gap {gap}  {cname:12s}  {a} ({ua}) vs {b} ({ub})"
              f"   [{shared} shared]")
    print(f"\n{len(unsafe)} of {len(worst)} inseparable pairs disagree on urgency")

    print("\n== ALL INSEPARABLE PAIRS ==")
    print("   shared  complaint     pair")
    for shared, _, cname, a, b in sorted(worst):
        print(f"   {shared:>6}  {cname:12s}  {a} vs {b}")
    print(f"\n{len(worst)} inseparable pairs across all pools")


if __name__ == "__main__":
    main()
