"""The fake ReviewPort passes the same contract as github_reviews."""

from __future__ import annotations

from adherence.adapters.fakes import FakeReviews
from adherence.domain.declaration import (
    Approval,
    Landing,
    NoLandingPR,
    ReviewsUnavailable,
)
from adherence.ports.review import ReviewPort
from tests.review_contract import (
    BROKEN,
    LANDED,
    OWNER,
    PR_AUTHOR,
    PUSHED,
    REVIEWED,
    REVIEWED_TEXT,
    ReviewContract,
)


class TestFakeReviews(ReviewContract):
    def reviews(self) -> ReviewPort:
        return FakeReviews(
            {
                LANDED: Landing(
                    PR_AUTHOR,
                    (Approval(OWNER, REVIEWED),),
                    reviewed=((REVIEWED, REVIEWED_TEXT),),
                ),
                PUSHED: NoLandingPR(PUSHED),
                BROKEN: ReviewsUnavailable("scripted: HTTP 502"),
            }
        )
