"""ReviewPort's contract, written once and run against every adapter.

A subclass supplies `reviews`: an adapter that knows three commits as the
contract names them -- LANDED, landed by a pull request PR_AUTHOR opened,
whose standing approvals are the one OWNER gave on REVIEWED (an earlier
approval its reviewer later withdrew, and a comment, do not stand);
PUSHED, which no pull request landed; and BROKEN, whose reviews the code
host cannot give.
"""

from __future__ import annotations

from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import (
    Approval,
    Landing,
    NoLandingPR,
    ReviewsUnavailable,
)
from adherence.ports.review import ReviewPort

LANDED = "1" * 40
PUSHED = "2" * 40
BROKEN = "3" * 40
REVIEWED = "4" * 40
PR_AUTHOR = "alice"
OWNER = "owner"
# An instant long past, by any clock.
PASSED = Deadline(0.0)


class ReviewContract:
    def reviews(self) -> ReviewPort:
        raise NotImplementedError("a contract subclass supplies its adapter")

    def test_approvals_of_a_landed_commit_are_its_prs_standing_approvals(
        self,
    ) -> None:
        """Given a commit a pull request landed, When its approvals are asked
        for, Then the answer is that PR's author and each approval that
        still stands, with its reviewer and the commit it reviewed."""
        answer = self.reviews().approvals(LANDED, None)

        assert answer == Landing(
            author=PR_AUTHOR, approvals=(Approval(OWNER, REVIEWED),)
        )

    def test_approvals_of_a_commit_no_pr_landed_are_no_landing(self) -> None:
        """Given a commit pushed with no pull request, When its approvals are
        asked for, Then the answer is NoLandingPR naming it."""
        assert self.reviews().approvals(PUSHED, None) == NoLandingPR(PUSHED)

    def test_approvals_the_code_host_cannot_give_are_unavailable(self) -> None:
        """Given a commit whose reviews the code host cannot give, When its
        approvals are asked for, Then the answer is the typed unavailable
        failure with a reason, never a landing."""
        answer = self.reviews().approvals(BROKEN, None)

        assert isinstance(answer, ReviewsUnavailable)
        assert answer.reason

    def test_approvals_past_the_deadline_time_out(self) -> None:
        """Given a deadline already passed, When approvals are asked for,
        Then the answer is TimedOut, not an overrun."""
        assert isinstance(self.reviews().approvals(LANDED, PASSED), TimedOut)
