"""The no_judge DecisionPort adapter (ARCHITECTURE.ARCH-ADHERENCE.md, Module
map: adapters/no_judge.py): every schema is answered with the typed
`unavailable` failure, so a stage without a judge reads every judged check
as coverage, never as a pass."""

from __future__ import annotations

from adherence.adapters.no_judge import NoJudge
from adherence.domain.model import Unit, UnitKind
from adherence.domain.questions import Question, Schema, State, Unavailable
from adherence.ports.decision import DecisionPort

UNIT = Unit("src/a.py", UnitKind.FUNCTION, "a", 1, 3, None)


def test_decide_without_a_judge_is_unavailable() -> None:
    """Given the no_judge adapter, When any schema is put to it, Then the
    answer is Unavailable with a reason, never a Decision."""
    judge: DecisionPort = NoJudge()
    schema = Schema((Question("implemented", ("yes", "no")),))

    answer = judge.decide(State(UNIT, "def a(): ..."), schema, None)

    assert isinstance(answer, Unavailable)
    assert answer.reason
