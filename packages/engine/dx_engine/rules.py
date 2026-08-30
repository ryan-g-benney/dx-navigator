"""Rule evaluation. Single-shot predicates over the answer set.

Rules never chain and never touch the ranking -- they emit actions only, which
is why deleting the scorer would not disturb them. See
docs/phase-0-architecture-position.md §1.
"""

from __future__ import annotations

from .kb import UNKNOWN, Clause, KnowledgeBase, Rule


def _holds(clause: Clause, answers: dict[str, str]) -> bool:
    got = answers.get(clause.var)
    if got is None or got == UNKNOWN:
        return False  # unknown never satisfies a clause; it is not a weak yes
    want = clause.value
    match clause.op:
        case "==":
            return got == want
        case "!=":
            return got != want
        case "in":
            return isinstance(want, list) and got in want
        case _:
            # Ordered comparisons need numeric values; our vocabularies are
            # categorical, so an ordered op on a category is an authoring error.
            raise ValueError(f"operator {clause.op!r} needs numeric values, got {got!r}")


def fired(kb: KnowledgeBase, complaint: str, answers: dict[str, str]) -> list[Rule]:
    """Every rule that fires for this complaint and answer set."""
    out = []
    for rule in kb.rules.values():
        if complaint not in rule.complaints:
            continue
        if not all(_holds(c, answers) for c in rule.all_of):
            continue
        if rule.any_of and sum(_holds(c, answers) for c in rule.any_of) < rule.min_matches:
            continue
        out.append(rule)
    return out
