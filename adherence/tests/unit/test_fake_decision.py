"""The fake DecisionPort passes the same contract as the decide adapter,
and so the one every judge passes."""

from __future__ import annotations

from adherence.adapters.fakes import FakeDecision
from adherence.domain.questions import Unavailable
from adherence.ports.decision import DecisionPort
from tests.decision_contract import DecisionContract


class TestFakeDecision(DecisionContract):
    def port(self) -> DecisionPort:
        return FakeDecision({})

    def unreachable(self) -> DecisionPort:
        return FakeDecision(Unavailable("the fake judge is scripted unreachable"))
