"""adapters/no_judge.py -- DecisionPort for a stage with no judge.

Every schema is answered with the typed `unavailable` failure, so the
judged checks read as coverage and never as a pass (ARCHITECTURE.ARCH-
ADHERENCE.md, Module map); past the Deadline the answer is TimedOut, as
every deadline-bound port's is. Nothing is spawned and nothing is read;
the clock is the edge's own.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.questions import (
    Availability,
    Decision,
    Rejected,
    Schema,
    State,
    Unavailable,
)

NO_JUDGE = "no judge is bound in this stage"


class NoJudge:
    """DecisionPort that answers every schema Unavailable, with the reason
    the composition root gives (why this stage has no judge)."""

    def __init__(
        self, reason: str = NO_JUDGE, *, clock: Callable[[], float] = time.time
    ) -> None:
        self.reason = reason
        self._clock = clock

    def availability(self) -> Availability:
        return Availability.UNAVAILABLE

    def decide(
        self, state: State, schema: Schema, deadline: Deadline | None
    ) -> Decision | Unavailable | Rejected | TimedOut:
        if deadline is not None and deadline.epoch_seconds <= self._clock():
            return TimedOut("ask the judge")
        return Unavailable(self.reason)
