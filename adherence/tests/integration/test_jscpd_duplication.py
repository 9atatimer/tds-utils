"""The jscpd DuplicationPort adapter: the shared contract over the real
tool, run as a subprocess outside the repository, and coverage when the
tool is absent. Skipped, never faked, when jscpd is not installed."""

from __future__ import annotations

from pathlib import Path

import pytest

from adherence.adapters.jscpd import JscpdDuplication
from adherence.domain.model import Metrics, MetricsUnavailable
from adherence.ports.duplication import DuplicationPort
from tests.duplication_contract import FIRST, SECOND, SOURCES, DuplicationContract

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


@pytest.mark.skipif(
    not JSCPD.is_file(),
    reason="jscpd is not installed (npm ci --ignore-scripts in adherence/)",
)
def test_measure_ignores_the_measured_sources_own_jscpd_markers() -> None:
    """Given two sources sharing a long stretch, one of them fenced by its
    own `jscpd:ignore-start` and `jscpd:ignore-end` comments, When clones are
    sought, Then the clone is still found: untrusted source never hides
    itself (Self-review R2)."""
    fenced = {
        FIRST: SOURCES[FIRST],
        SECOND: b"# jscpd:ignore-start\n" + SOURCES[SECOND] + b"# jscpd:ignore-end\n",
    }

    answer = JscpdDuplication(command=(str(JSCPD),)).measure(fenced, None)

    assert isinstance(answer, Metrics), answer
    assert [(c.first.path, c.second.path) for c in answer.clones] == [(FIRST, SECOND)]
