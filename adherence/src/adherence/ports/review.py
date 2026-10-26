"""ports/review.py -- ReviewPort: who approved a change, from the code host.

github_reviews in CI, no_reviews (Unknown) on the laptop, in the hook and
in the cloud, and a fake (ARCHITECTURE.ARCH-ADHERENCE.md, Seams). A
failure is the typed ReviewsUnavailable and counts as no approvals.
"""

from __future__ import annotations

from typing import Protocol

from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import (
    Landing,
    NoLandingPR,
    ReviewsUnavailable,
    Unknown,
)


class ReviewPort(Protocol):
    def approvals(
        self, commit: str, deadline: Deadline | None
    ) -> Landing | NoLandingPR | Unknown | ReviewsUnavailable | TimedOut:
        """The pull request that landed the commit, with its author and its
        approving reviews; NoLandingPR when none did."""
        ...
