"""Session state machine. A pure function over a serialisable value.

    step(kb, state, var, answer) -> state
    undo(state) -> state

State is the answer log and nothing else, so undo is dropping the last entry and
belief is recomputed. There is nothing to unwind. The knowledge base is an
input, never part of the state -- it is versioned separately and must not be
serialised into every session row.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum

from .kb import KnowledgeBase
from .rules import fired
from .score import EVIDENCE_FLOOR, Ranked, rank
from .select import burden, next_question

MAX_QUESTIONS = 10  # hard cap, brief §3
# ponytail: lead margin is a guess. Fit it against the eval once independent
# vignettes exist; do not let it quietly become a magic constant.
LEAD_MARGIN = 0.12


class Stop(str, Enum):
    ONGOING = "ongoing"
    EMERGENCY = "emergency_escalation"
    CONFIDENT = "clear_leader"
    EXHAUSTED = "no_discriminating_question_left"
    BUDGET = "question_cap_reached"
    INSUFFICIENT = "insufficient_information"


@dataclass(frozen=True)
class State:
    complaint: str
    answers: dict[str, str] = field(default_factory=dict)
    asked: tuple[str, ...] = ()

    def with_answer(self, var: str, value: str) -> "State":
        return replace(self, answers={**self.answers, var: value}, asked=(*self.asked, var))


@dataclass(frozen=True)
class View:
    state: State
    ranked: list[Ranked]
    fired_rules: tuple[str, ...]
    stop: Stop
    question: str | None
    burden: int
    # Emergency conditions in the pool that the answers so far have NOT argued
    # against. Required by brief §7 ("red flags excluded and outstanding") and
    # by a concrete failure: a dissection vignette escalated after 2 questions
    # with acute coronary syndrome ranked first, because the short-circuit fired
    # before the differential had separated. Escalating was right; presenting
    # ACS as the answer was not -- ACS treatment harms a dissection.
    emergency_outstanding: tuple[str, ...] = ()
    provisional: bool = False


def _emergency_outstanding(kb: KnowledgeBase, state: State,
                           ranked: list[Ranked]) -> tuple[str, ...]:
    scores = {r.slug: r for r in ranked}
    out = []
    for slug in kb.complaints[state.complaint].pool:
        if kb.conditions[slug].urgency.value != "emergency":
            continue
        r = scores.get(slug)
        if r is None or r.normalised >= 0 or r.insufficient:
            out.append(slug)  # not yet argued against
    return tuple(out)


def _stop_reason(kb: KnowledgeBase, state: State, ranked: list[Ranked],
                 rules, question: str | None) -> Stop:
    if any(r.emit.urgency.value == "emergency" for r in rules):
        return Stop.EMERGENCY  # short-circuits everything else
    if question is None:
        top = ranked[0] if ranked else None
        if top and not top.insufficient and top.normalised > 0:
            return Stop.EXHAUSTED
        return Stop.INSUFFICIENT
    if len(state.asked) >= MAX_QUESTIONS:
        top = ranked[0] if ranked else None
        return Stop.BUDGET if top and not top.insufficient else Stop.INSUFFICIENT
    if len(ranked) >= 2:
        lead = ranked[0].confidence_weighted - ranked[1].confidence_weighted
        if (lead >= LEAD_MARGIN and ranked[0].evidence >= EVIDENCE_FLOOR
                and ranked[0].confidence_weighted > 0):
            return Stop.CONFIDENT
    return Stop.ONGOING


def view(kb: KnowledgeBase, state: State) -> View:
    ranked = rank(kb, state.complaint, state.answers, top=len(kb.complaints[state.complaint].pool))
    rules = fired(kb, state.complaint, state.answers)
    question = next_question(kb, state.complaint, state.answers, ranked[:5])
    stop = _stop_reason(kb, state, ranked[:5], rules, question)
    outstanding = _emergency_outstanding(kb, state, ranked)
    # An escalation reached before the differential separated must not be
    # presented as an answer. Mark it, so the report leads with the rule.
    provisional = stop is Stop.EMERGENCY and (
        not ranked or ranked[0].insufficient or len(outstanding) > 1
    )
    return View(state, ranked[:5], tuple(r.id for r in rules), stop,
                None if stop is not Stop.ONGOING else question,
                burden(kb, state.answers), outstanding, provisional)


def start(complaint: str) -> State:
    return State(complaint=complaint)


def step(kb: KnowledgeBase, state: State, var: str, answer: str) -> State:
    if var not in kb.variables:
        raise ValueError(f"unknown variable {var!r}")
    if answer not in kb.variables[var].values:
        raise ValueError(f"{answer!r} is not a legal value for {var!r}")
    return state.with_answer(var, answer)


def undo(state: State) -> State:
    if not state.asked:
        return state
    last, *_ = state.asked[-1:]
    answers = {k: v for k, v in state.answers.items() if k != last}
    return replace(state, answers=answers, asked=state.asked[:-1])
