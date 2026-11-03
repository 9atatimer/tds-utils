"""The fake ComplexityPort passes the same contract as the lizard adapter."""

from __future__ import annotations

from adherence.adapters.fakes import FakeComplexity
from adherence.ports.complexity import ComplexityPort
from tests.complexity_contract import MEASURED, ComplexityContract


class TestFakeComplexity(ComplexityContract):
    def port(self) -> ComplexityPort:
        return FakeComplexity(MEASURED)
