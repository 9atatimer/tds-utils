"""ports/decision.py -- DecisionPort: who answers a judged question.

The decide client, a local arena, the no_judge adapter and a fake sit
behind it (ARCHITECTURE.ARCH-ADHERENCE.md, Seams). A failure is a typed
value: Unavailable, Rejected for an input the judge refuses, or TimedOut
past the Deadline. Each says whether it binds a judge at all, which a
report's identity carries (Module map: domain/report.py).
"""

from __future__ import annotations

from typing import Protocol

from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.questions import (
    Availability,
    Decision,
    Rejected,
    Schema,
    State,
    Unavailable,
)


class DecisionPort(Protocol):
    def availability(self) -> Availability:
        """Whether a judge is bound behind the port at all: the composition
        root's choice, before any question is asked."""
        ...

    def decide(
        self, state: State, schema: Schema, deadline: Deadline | None
    ) -> Decision | Unavailable | Rejected | TimedOut:
        """A probability per allowed answer of every question in the schema."""
        ...
