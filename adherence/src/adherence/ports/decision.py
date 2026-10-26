"""ports/decision.py -- DecisionPort: who answers a judged question.

The decide client, a local arena, the no_judge adapter and a fake sit
behind it (ARCHITECTURE.ARCH-ADHERENCE.md, Seams). A failure is a typed
value: Unavailable, Rejected for an input the judge refuses, or TimedOut
past the Deadline.
"""

from __future__ import annotations

from typing import Protocol

from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.questions import Decision, Rejected, Schema, State, Unavailable


class DecisionPort(Protocol):
    def decide(
        self, state: State, schema: Schema, deadline: Deadline | None
    ) -> Decision | Unavailable | Rejected | TimedOut:
        """A probability per allowed answer of every question in the schema."""
        ...
