"""The lizard ComplexityPort adapter: the shared contract over the real
tool, run as a subprocess outside the repository, and coverage when the
tool is absent. Skipped, never faked, when lizard is not installed."""

from __future__ import annotations

import importlib.util

import pytest

from adherence.adapters.lizard import LizardComplexity
from adherence.domain.model import Metrics, MetricsUnavailable
from adherence.ports.complexity import ComplexityPort
from tests.complexity_contract import RULES, SOURCES, ComplexityContract

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


FORGIVEN = "src/pkg/forgiven.py"
BRANCHY = (
    b"    if x:\n        return 1\n    elif x > 2:\n        return 2\n    return 3\n"
)


@pytest.mark.skipif(LIZARD_ABSENT, reason="lizard is not installed (uv sync)")
def test_measure_ignores_the_measured_sources_own_lizard_directives() -> None:
    """Given functions under the measured source's own `#lizard forgive`
    and `GENERATED CODE` comments, When complexity is measured, Then each is
    still measured: untrusted source never exempts itself (Self-review R1)."""
    sources = {
        FORGIVEN: (
            b"def forgiven(x):\n"
            b"    # #lizard forgive\n" + BRANCHY + b"\n\n"
            b"def generated(x):\n"
            b"    # GENERATED CODE -- do not measure\n" + BRANCHY + b"\n\n"
            b"def after(x):\n" + BRANCHY
        ),
    }

    answer = LizardComplexity().measure(sources, None)

    assert isinstance(answer, Metrics), answer
    assert {(c.symbol, c.value) for c in answer.complexity} == {
        ("forgiven", 3),
        ("generated", 3),
        ("after", 3),
    }


@pytest.mark.skipif(LIZARD_ABSENT, reason="lizard is not installed (uv sync)")
def test_measure_of_a_path_holding_a_newline_still_measures_it() -> None:
    """Given a source whose repository path holds a newline beside an
    ordinary one, When complexity is measured, Then the functions of both
    are named by their repository paths: no path splits the file list and
    drops its functions (Self-review R9)."""
    odd = "src/pkg/odd\nname.py"
    sources = {odd: b"def odd(x):\n" + BRANCHY, RULES: b"def plain(x):\n" + BRANCHY}

    answer = LizardComplexity().measure(sources, None)

    assert isinstance(answer, Metrics), answer
    assert {(c.path, c.symbol) for c in answer.complexity} == {
        (odd, "odd"),
        (RULES, "plain"),
    }
