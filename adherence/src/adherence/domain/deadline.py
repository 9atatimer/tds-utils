"""domain/deadline.py -- when a bounded run must end, and the answer past it.

The entry point computes the Deadline; only adapters compare it to the
clock, and an adapter that cannot finish by it returns TimedOut. The core
reads no time (ARCHITECTURE.ARCH-ADHERENCE.md, Seams).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Deadline:
    """The instant a bounded run must end, in seconds since the epoch."""

    epoch_seconds: float


@dataclass(frozen=True, slots=True)
class TimedOut:
    """A deadline-bound port's answer when it could not finish in time."""

    operation: str
