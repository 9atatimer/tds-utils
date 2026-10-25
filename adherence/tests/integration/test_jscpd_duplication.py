"""The jscpd DuplicationPort adapter: the shared contract over the real
tool, run as a subprocess outside the repository, and coverage when the
tool is absent. Skipped, never faked, when jscpd is not installed."""

from __future__ import annotations

from pathlib import Path

import pytest
from adherence.adapters.jscpd import JscpdDuplication

from adherence.domain.model import MetricsUnavailable
from adherence.ports.duplication import DuplicationPort
from tests.duplication_contract import SOURCES, DuplicationContract

JSCPD = Path(__file__).resolve().parents[2] / "node_modules" / ".bin" / "jscpd"


@pytest.mark.skipif(
    not JSCPD.is_file(),
    reason="jscpd is not installed (npm ci --ignore-scripts in adherence/)",
)
class TestJscpdDuplication(DuplicationContract):
    def port(self) -> DuplicationPort:
        return JscpdDuplication(command=(str(JSCPD),))


def test_measure_with_the_tool_absent_is_unavailable_naming_it() -> None:
    """Given a jscpd command that does not exist, When clones are sought,
    Then the answer is unavailable and names the tool, never an empty
    result."""
    port = JscpdDuplication(command=("/nonexistent/adherence-jscpd",))

    answer = port.measure(SOURCES, None)

    assert isinstance(answer, MetricsUnavailable), answer
    assert "jscpd" in answer.reason
