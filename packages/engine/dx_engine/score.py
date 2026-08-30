"""Signed feature matching. No probabilities.

score = sum over variables answered AND stated by the condition:
          +w on match, -w on mismatch, 0 on unknown or unstated
normalised = score / sum |w|   -> [-1, +1]
evidence   = number of contributing terms

Every weight is 1.0 today. When likelihoods arrive, weights become the log of
the authored ordinal and this file does not change -- see
docs/phase-0-simplified-engine.md §5.
"""

from __future__ import annotations

from dataclasses import dataclass

from .kb import UNKNOWN, Complaint, KnowledgeBase

EVIDENCE_FLOOR = 3  # below this a condition is not eligible for rank 1


@dataclass(frozen=True)
class Ranked:
    slug: str
    normalised: float
    evidence: int
    matched: tuple[str, ...]
    mismatched: tuple[str, ...]

    @property
    def insufficient(self) -> bool:
        return self.evidence < EVIDENCE_FLOOR


def score_condition(kb: KnowledgeBase, slug: str, answers: dict[str, str]) -> Ranked:
    cond = kb.conditions[slug]
    total = weight_sum = 0.0
    matched: list[str] = []
    mismatched: list[str] = []
    for var, answer in answers.items():
        feat = cond.features.get(var)
        if feat is None or answer == UNKNOWN:
            continue  # unstated and unknown are both genuine no-ops
        weight_sum += abs(feat.weight)
        if answer in feat.expect:
            total += feat.weight
            matched.append(var)
        else:
            total -= feat.weight
            mismatched.append(var)
    normalised = total / weight_sum if weight_sum else 0.0
    return Ranked(slug, normalised, len(matched) + len(mismatched),
                  tuple(matched), tuple(mismatched))


def rank(kb: KnowledgeBase, complaint: str, answers: dict[str, str],
         top: int = 5) -> list[Ranked]:
    """Rank a complaint's pool. Sorted by score, then by weight of evidence."""
    comp: Complaint = kb.complaints[complaint]
    scored = [score_condition(kb, s, answers) for s in comp.pool]
    scored.sort(key=lambda r: (r.insufficient, -r.normalised, -r.evidence, r.slug))
    return scored[:top]


def flip_adjacent(kb: KnowledgeBase, complaint: str, answers: dict[str, str]
                  ) -> list[tuple[str, str, str, str]]:
    """Conditions one answer away from taking the top slot.

    Returns (variable, alternative_value, condition_that_would_lead, current_leader).
    This is the product: it names the answer the ranking hinges on, which is more
    use to a clinician than a confidence number.
    """
    top = rank(kb, complaint, answers, top=1)
    if not top:
        return []
    leader = top[0].slug
    out: list[tuple[str, str, str, str]] = []
    for var, given in answers.items():
        for alt in kb.variables[var].values:
            if alt == given:
                continue
            probe = dict(answers)
            probe[var] = alt
            new = rank(kb, complaint, probe, top=1)
            if new and new[0].slug != leader:
                out.append((var, alt, new[0].slug, leader))
    return out
