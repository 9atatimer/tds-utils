"""adapters/no_reviews.py -- ReviewPort for a stage that reads no code host.

The laptop, the hook and the cloud cannot know who approved a landing, so
every answer is Unknown and the landed declaration stands there; the gate,
in CI, is where approvals are read (ARCHITECTURE.ARCH-ADHERENCE.md, Module
map). Nothing is spawned and nothing is read.
"""

from __future__ import annotations

from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import (
    Landing,
    NoLandingPR,
    ReviewsUnavailable,
    Unknown,
)

NO_REVIEWS = "no code host's reviews are read in this stage"


class NoReviews:
    """ReviewPort that answers every commit Unknown."""

    def approvals(
        self, commit: str, deadline: Deadline | None
    ) -> Landing | NoLandingPR | Unknown | ReviewsUnavailable | TimedOut:
        return Unknown(NO_REVIEWS)
