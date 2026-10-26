"""DecisionPort's contract, written once and run against every adapter.

What every judge promises whatever it answers: TimedOut rather than
overrun a passed deadline (ARCHITECTURE.ARCH-ADHERENCE.md, Seams: the
deadline-bound ports). A subclass supplies `port`; the decide adapter
joins in task-066.
"""

from __future__ import annotations

from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.model import Unit, UnitKind
from adherence.domain.questions import Question, Schema, State
from adherence.ports.decision import DecisionPort

UNIT = Unit("src/a.py", UnitKind.FUNCTION, "a", 1, 3, None)
SCHEMA = Schema((Question("implemented", ("yes", "no")),))
# An instant every clock, real or faked, has long passed.
PASSED = Deadline(epoch_seconds=1.0)


class DecisionContract:
    def port(self) -> DecisionPort:
        raise NotImplementedError("a contract subclass supplies its adapter")

    def test_decide_past_the_deadline_times_out(self) -> None:
        """Given a deadline already passed, When a schema is put to the
        judge, Then the answer is TimedOut, not a decision or a failure."""
        answer = self.port().decide(State(UNIT, "def a(): ..."), SCHEMA, PASSED)

        assert isinstance(answer, TimedOut)
