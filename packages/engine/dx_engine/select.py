"""Question selection: split the leaders, cheaply, red flags first.

Without a probability distribution there is no expected information gain. The
substitute is to prefer the unanswered variable whose values most evenly
partition the current leaders -- the same calculation as information gain with
every weight set to 1, which is what the rest of the engine already assumes.

Red flags are not optimised. They are asked because policy says so.
"""

from __future__ import annotations

from .kb import UNKNOWN, KnowledgeBase, Role
from .score import Ranked

UNSTATED = "\x00unstated"
MIN_SPLIT = 0.25    # below this a question cannot meaningfully reorder leaders
COST_WEIGHT = 0.25  # burden penalty per cost unit


def _split_quality(kb: KnowledgeBase, var: str, leaders: list[str]) -> float:
    """1 - sum(p^2) over the groups this variable sorts the leaders into.

    0 when every leader expects the same thing (the question cannot reorder
    them); approaches 1 as the split becomes even.
    """
    groups: dict[object, int] = {}
    for slug in leaders:
        feat = kb.conditions[slug].features.get(var)
        key = frozenset(feat.expect) if feat else UNSTATED
        groups[key] = groups.get(key, 0) + 1
    n = len(leaders)
    return 1.0 - sum((c / n) ** 2 for c in groups.values())


def _outstanding_red_flags(kb: KnowledgeBase, ranked: list[Ranked],
                           answers: dict[str, str]) -> list[str]:
    """Red-flag variables of still-plausible conditions that nobody has asked about."""
    out: list[str] = []
    for r in ranked:
        if r.normalised < 0:
            continue  # already argued against; not still plausible
        for var in kb.conditions[r.slug].red_flag_features:
            if var not in answers and var not in out:
                out.append(var)
    return out


def next_question(kb: KnowledgeBase, complaint: str, answers: dict[str, str],
                  ranked: list[Ranked]) -> str | None:
    """The next variable to ask, or None when nothing left can change the ranking."""
    pool = kb.complaints[complaint].pool

    # Tier 1: outstanding red flags on plausible conditions. Not optimised --
    # this is the "force the red flag they'd have skipped on a busy Friday" path.
    for var in _outstanding_red_flags(kb, ranked, answers):
        if kb.variables[var].role is not Role.DISPOSITION:
            return var

    # Tier 2: best split per unit of burden.
    leaders = [r.slug for r in ranked] or pool
    best, best_value = None, 0.0
    for name, var in kb.variables.items():
        if name in answers or var.role is Role.DISPOSITION:
            continue
        if not any(name in kb.conditions[s].features for s in pool):
            continue
        quality = _split_quality(kb, name, leaders)
        if quality < MIN_SPLIT:
            continue  # cannot meaningfully reorder the leaders; pure burden
        # Cost is a mild penalty, not a divisor. A divisor demoted examination
        # so hard that the question which actually settles the case was never
        # asked before the budget ran out.
        value = quality / (1 + COST_WEIGHT * var.cost)
        if value > best_value or (value == best_value and best and name < best):
            best, best_value = name, value
    return best


def burden(kb: KnowledgeBase, answers: dict[str, str]) -> int:
    """Total cost of the questions asked. Watched for drift, per brief §5."""
    return sum(kb.variables[v].cost for v in answers if v in kb.variables)


def is_no_op(answer: str) -> bool:
    return answer == UNKNOWN
