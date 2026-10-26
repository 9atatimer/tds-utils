"""The fake DecisionPort passes the same contract as every judge."""

from __future__ import annotations

from adherence.adapters.fakes import FakeDecision
from adherence.domain.questions import Unavailable
from adherence.ports.decision import DecisionPort
from tests.decision_contract import DecisionContract


class TestFakeDecision(DecisionContract):
    def port(self) -> DecisionPort:
        return FakeDecision(Unavailable("faked"))
