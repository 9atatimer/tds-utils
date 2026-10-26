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
from adherence.domain.questions import Decision, Schema, State, Unavailable

NO_JUDGE = "no judge is bound in this stage"


class NoJudge:
    """DecisionPort that answers every schema Unavailable."""

    def __init__(self, *, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock

    def decide(
        self, state: State, schema: Schema, deadline: Deadline | None
    ) -> Decision | Unavailable | TimedOut:
        if deadline is not None and deadline.epoch_seconds <= self._clock():
            return TimedOut("ask the judge")
        return Unavailable(NO_JUDGE)
