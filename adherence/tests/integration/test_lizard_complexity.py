"""The lizard ComplexityPort adapter: the shared contract over the real
tool, run as a subprocess outside the repository, and coverage when the
tool is absent. Skipped, never faked, when lizard is not installed."""

from __future__ import annotations

import importlib.util

import pytest
from adherence.adapters.lizard import LizardComplexity

from adherence.domain.model import MetricsUnavailable
from adherence.ports.complexity import ComplexityPort
from tests.complexity_contract import SOURCES, ComplexityContract

LIZARD_ABSENT = importlib.util.find_spec("lizard") is None


@pytest.mark.skipif(LIZARD_ABSENT, reason="lizard is not installed (uv sync)")
class TestLizardComplexity(ComplexityContract):
    def port(self) -> ComplexityPort:
        return LizardComplexity()


def test_measure_with_the_tool_absent_is_unavailable_naming_it() -> None:
    """Given a lizard command that does not exist, When complexity is
    measured, Then the answer is unavailable and names the tool, never an
    empty measurement."""
    port = LizardComplexity(command=("/nonexistent/adherence-lizard",))

    answer = port.measure(SOURCES, None)

    assert isinstance(answer, MetricsUnavailable), answer
    assert "lizard" in answer.reason
