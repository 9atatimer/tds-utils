"""ReviewPort's contract, written once and run against every adapter.

What every code host's reviews promise whatever they answer: TimedOut
rather than overrun a passed deadline (ARCHITECTURE.ARCH-ADHERENCE.md,
Seams: the deadline-bound ports). A subclass supplies `port`; the
github_reviews adapter joins in task-066.
"""

from __future__ import annotations

from adherence.domain.deadline import Deadline, TimedOut
from adherence.ports.review import ReviewPort

COMMIT = "a" * 40
# An instant every clock, real or faked, has long passed.
PASSED = Deadline(epoch_seconds=1.0)


class ReviewContract:
    def port(self) -> ReviewPort:
        raise NotImplementedError("a contract subclass supplies its adapter")

    def test_approvals_past_the_deadline_time_out(self) -> None:
        """Given a deadline already passed, When a commit's approvals are
        asked for, Then the answer is TimedOut, not a landing or Unknown."""
        answer = self.port().approvals(COMMIT, PASSED)

        assert isinstance(answer, TimedOut)
