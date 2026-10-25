"""DuplicationPort's contract, written once and run against every adapter.

Language-neutral promises: nothing from nothing, a stretch two sources
share named once by both repository paths and their lines, and TimedOut
rather than overrun a passed deadline. A subclass supplies `port`.
"""

from __future__ import annotations

from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.model import Clone, Metrics, Span
from adherence.ports.duplication import DuplicationPort

FIRST = "src/pkg/first.py"
SECOND = "src/pkg/second.py"
_SHARED = b"".join(b"    total = total + values[%d] * %d\n" % (i, i) for i in range(12))
SOURCES = {
    FIRST: b"def first(values):\n    total = 0\n" + _SHARED + b"    return total\n",
    SECOND: (
        b"import math\n\n\ndef second(values):\n    total = 0\n"
        + _SHARED
        + b"    return total\n"
    ),
    "src/pkg/alone.py": b"def alone():\n    return 1\n",
}
# The one stretch the two share: the whole of `first`, and `second` from
# its definition on.
SHARED = Clone(Span(FIRST, 1, 15), Span(SECOND, 4, 18), 15)


class DuplicationContract:
    def port(self) -> DuplicationPort:
        raise NotImplementedError("a contract subclass supplies its adapter")

    def test_measure_of_nothing_is_empty(self) -> None:
        """Given no sources, When clones are sought, Then none is found."""
        answer = self.port().measure({}, None)

        assert isinstance(answer, Metrics), answer
        assert answer.clones == ()

    def test_measure_names_a_shared_stretch_once_by_both_paths(self) -> None:
        """Given two sources sharing a long stretch and one sharing nothing,
        When clones are sought, Then one clone names both stretches, the
        first path first, and how many lines they share."""
        answer = self.port().measure(SOURCES, None)

        assert isinstance(answer, Metrics), answer
        assert answer.clones == (SHARED,)

    def test_measure_past_the_deadline_times_out(self) -> None:
        """Given a deadline already passed, When clones are sought, Then the
        answer is TimedOut, not a partial result."""
        answer = self.port().measure(SOURCES, Deadline(epoch_seconds=0.0))

        assert isinstance(answer, TimedOut)
