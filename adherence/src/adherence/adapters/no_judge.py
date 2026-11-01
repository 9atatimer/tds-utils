"""adapters/no_judge.py -- DecisionPort for a stage with no judge.

Every schema is answered with the typed `unavailable` failure, so the
judged checks read as coverage and never as a pass (ARCHITECTURE.ARCH-
ADHERENCE.md, Module map). Nothing is spawned and nothing is read.
"""

from __future__ import annotations

from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.questions import Decision, Schema, State, Unavailable

NO_JUDGE = "no judge is bound in this stage"


class NoJudge:
    """DecisionPort that answers every schema Unavailable."""

    def decide(
        self, state: State, schema: Schema, deadline: Deadline | None
    ) -> Decision | Unavailable | TimedOut:
        return Unavailable(NO_JUDGE)
