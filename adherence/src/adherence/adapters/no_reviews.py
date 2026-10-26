"""adapters/no_reviews.py -- ReviewPort for a stage that reads no code host.

The laptop, the hook and the cloud cannot know who approved a landing, so
every answer is Unknown and the landed declaration stands there; the gate,
in CI, is where approvals are read (ARCHITECTURE.ARCH-ADHERENCE.md, Module
map); past the Deadline the answer is TimedOut, as every deadline-bound
port's is. Nothing is spawned and nothing is read; the clock is the edge's
own.
"""

from __future__ import annotations

import time
from collections.abc import Callable

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

    def __init__(self, *, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock

    def approvals(
        self, commit: str, deadline: Deadline | None
    ) -> Landing | NoLandingPR | Unknown | ReviewsUnavailable | TimedOut:
        if deadline is not None and deadline.epoch_seconds <= self._clock():
            return TimedOut("read the reviews")
        return Unknown(NO_REVIEWS)
