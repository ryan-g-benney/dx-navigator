#!/usr/bin/env python3
"""Knowledge-base validator. Exit 1 on any error.

Structural lints (brief §4) plus the extensional lattice lints from
docs/phase-0-simplified-engine.md -- identical signatures and strict subsumption
are authoring bugs that nothing else catches.
"""

from __future__ import annotations

import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "engine"))

from dx_engine.kb import KnowledgeBase, Origin, Role, Urgency, load  # noqa: E402

UNSTATED = object()

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []
warnings: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


def check_refs(kb: KnowledgeBase) -> None:
    for slug, c in kb.conditions.items():
        if c.origin is Origin.MACHINE_CANDIDATE:
            err(f"{slug}: origin=machine_candidate must not reach data/ -- promote it in .workbench first")
        for var, feat in c.features.items():
            if var not in kb.variables:
                err(f"{slug}: feature {var!r} is not a declared variable")
                continue
            legal = set(kb.variables[var].values)
            for v in feat.expect:
                if v not in legal:
                    err(f"{slug}.{var}: {v!r} not among {sorted(legal)}")
            if feat.source not in kb.sources:
                err(f"{slug}.{var}: unknown source {feat.source!r}")
        for rf in c.red_flag_features:
            if rf not in c.features:
                err(f"{slug}: red_flag_feature {rf!r} not in its own features")
    for rid, r in kb.rules.items():
        if r.emit.source not in kb.sources:
            err(f"rule {rid}: unknown source {r.emit.source!r}")
        for clause in [*r.all_of, *r.any_of]:
            if clause.var not in kb.variables:
                err(f"rule {rid}: clause var {clause.var!r} is not a declared variable")


def check_graph(kb: KnowledgeBase) -> None:
    nodes = set(kb.conditions) | set(kb.categories)
    for slug in nodes:
        for parent in kb.node_parents(slug):
            if parent not in nodes:
                err(f"{slug}: parent {parent!r} does not exist")
    # cycles
    WHITE, GREY, BLACK = 0, 1, 2
    colour = dict.fromkeys(nodes, WHITE)

    def visit(n: str, trail: list[str]) -> None:
        if colour.get(n) == GREY:
            err(f"DAG cycle: {' -> '.join([*trail, n])}")
            return
        if colour.get(n) == BLACK:
            return
        colour[n] = GREY
        for p in kb.node_parents(n):
            if p in nodes:
                visit(p, [*trail, n])
        colour[n] = BLACK

    for n in nodes:
        visit(n, [])
    # orphans: every condition must reach a root through some parent chain
    for slug, c in kb.conditions.items():
        if not c.parents:
            err(f"{slug}: orphan condition, no parent")


def check_safety(kb: KnowledgeBase) -> None:
    for slug, c in kb.conditions.items():
        if c.urgency is Urgency.EMERGENCY and not c.red_flag_features:
            err(f"{slug}: urgency=emergency with no red_flag_features")


def check_lattice(kb: KnowledgeBase) -> None:
    """Extensional checks. See docs/phase-0-simplified-engine.md §3."""
    sig = {
        slug: frozenset((v, frozenset(f.expect)) for v, f in c.features.items())
        for slug, c in kb.conditions.items()
        if c.features
    }
    for a, b in combinations(sorted(sig), 2):
        if sig[a] == sig[b]:
            err(f"identical signatures: {a} and {b} can never be told apart -- add a discriminating feature or merge")
        elif sig[a] < sig[b]:
            warn(f"{a}'s evidence profile is a strict subset of {b}'s -- {a} may never outrank it")
        elif sig[b] < sig[a]:
            warn(f"{b}'s evidence profile is a strict subset of {a}'s -- {b} may never outrank it")
    # Discrimination floor. A variable is dead weight only if EVERY condition
    # treats it identically. Conditions that leave it unstated form their own
    # group -- a variable stated by some and not others still separates them.
    for name, var in kb.variables.items():
        if var.role is Role.DISPOSITION:
            continue  # disposition variables are not meant to discriminate
        groups: set[object] = set()
        for c in kb.conditions.values():
            feat = c.features.get(name)
            groups.add(frozenset(feat.expect) if feat else UNSTATED)
        if len(groups) < 2:
            warn(f"variable {name!r}: every condition treats it identically -- cannot discriminate")


def main() -> int:
    data = ROOT / "data"
    try:
        kb = load(data)
    except Exception as exc:  # loader failures are fatal and must be loud
        print(f"LOAD FAILED\n{exc}", file=sys.stderr)
        return 1

    for check in (check_refs, check_graph, check_safety, check_lattice):
        check(kb)

    print(f"kb version {kb.version_hash}")
    print(
        f"  {len(kb.conditions)} conditions, {len(kb.categories)} categories, "
        f"{len(kb.variables)} variables, {len(kb.rules)} rules, {len(kb.sources)} sources"
    )
    for w in warnings:
        print(f"  WARN  {w}")
    for e in errors:
        print(f"  ERROR {e}", file=sys.stderr)
    if errors:
        print(f"\n{len(errors)} error(s)", file=sys.stderr)
        return 1
    print("  ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
