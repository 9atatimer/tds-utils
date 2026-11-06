"""DecisionPort's contract, written once and run against every adapter.

DeadlineBoundDecisionContract is what every judge promises whatever it
answers: TimedOut rather than overrun a passed deadline
(ARCHITECTURE.ARCH-ADHERENCE.md, Seams: the deadline-bound ports). A
subclass supplies `port`; no_judge, which answers nothing, runs this part
alone.

DecisionContract adds what a judge that answers promises (the
decision-models skill, Testing): every question of the schema answered
with a probability per option; the typed failures -- Rejected for an input
the judge refuses, Unavailable for a judge that cannot be reached --
returned as values, never raised. A subclass supplies `port` and
`unreachable`.
"""

from __future__ import annotations

import pytest

from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.model import Layer, Unit, UnitKind
from adherence.domain.questions import (
    THEN_ASSERTED,
    TWO_JOBS,
    Decision,
    Rejected,
    Schema,
    State,
    Unavailable,
    hand_rolled_question,
)
from adherence.ports.decision import DecisionPort

UNIT = Unit("src/app/domain/rules.py", UnitKind.FUNCTION, "price", 1, 4, Layer.DOMAIN)
STATE = State(
    UNIT,
    "def price(order):\n    return order.total * 1.2",
    {"two_jobs.1": "declared layer: domain, whose job is rules"},
)
# One question of each kind.
SCHEMA = Schema(
    {
        "two_jobs.1": TWO_JOBS,
        "hand_rolled.1": hand_rolled_question(2),
        "then_asserted.1": THEN_ASSERTED,
    }
)
# An instant every clock, real or faked, has long passed.
PASSED = Deadline(epoch_seconds=1.0)


class DeadlineBoundDecisionContract:
    def port(self) -> DecisionPort:
        raise NotImplementedError("a contract subclass supplies its adapter")

    def test_decide_past_the_deadline_times_out(self) -> None:
        """Given a deadline already passed, When a schema is put to the
        judge, Then the answer is TimedOut, not a decision or a failure."""
        answer = self.port().decide(STATE, SCHEMA, PASSED)

        assert isinstance(answer, TimedOut)


class DecisionContract(DeadlineBoundDecisionContract):
    def unreachable(self) -> DecisionPort:
        raise NotImplementedError("a contract subclass supplies an unreachable one")

    def test_decide_answers_every_question_with_a_probability_per_option(
        self,
    ) -> None:
        """Given a schema with a binary, a choice and a score question, When
        it is put to the judge, Then every question is answered with a
        probability between 0 and 1 for each of its options, a calibrated
        answer's summing to 1."""
        answer = self.port().decide(STATE, SCHEMA, None)

        assert isinstance(answer, Decision), answer
        assert set(answer.probabilities) == set(SCHEMA.questions)
        for key, question in SCHEMA.questions.items():
            probabilities = answer.probabilities[key]
            assert set(probabilities) == set(question.options), key
            assert all(0.0 <= p <= 1.0 for p in probabilities.values()), key
            if key not in answer.uncalibrated:
                assert sum(probabilities.values()) == pytest.approx(1.0, abs=0.02)

    def test_decide_of_a_schema_with_no_question_is_rejected(self) -> None:
        """Given a schema with no question, When it is put to the judge, Then
        the answer is Rejected with a reason, never a Decision."""
        answer = self.port().decide(STATE, Schema({}), None)

        assert isinstance(answer, Rejected), answer
        assert answer.reason

    def test_decide_with_the_judge_unreachable_is_unavailable(self) -> None:
        """Given a judge that cannot be reached, When a schema is put to it,
        Then the answer is Unavailable with a reason, not an exception."""
        answer = self.unreachable().decide(STATE, SCHEMA, None)

        assert isinstance(answer, Unavailable), answer
        assert answer.reason

    def test_decide_at_the_epoch_deadline_times_out(self) -> None:
        """Given a deadline already passed, When a schema is put to the
        judge, Then the answer is TimedOut and the judge is not asked."""
        answer = self.port().decide(STATE, SCHEMA, Deadline(epoch_seconds=0.0))

        assert isinstance(answer, TimedOut), answer
