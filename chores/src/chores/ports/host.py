"""Host facts the admission policy needs (CHORES.DESIGN.md Subsystem 2)."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class ClockPort(Protocol):
    def now_local(self) -> datetime:
        """Naive local wall-clock time (schedules are evaluated on it)."""
        ...

    def now_utc(self) -> datetime:
        """Naive UTC time (records and ids carry it)."""
        ...

    def local_from_utc(self, at: datetime) -> datetime:
        """Convert a naive UTC instant to naive local wall-clock time."""
        ...


class PowerPort(Protocol):
    def on_battery(self) -> bool: ...


class NetworkPort(Protocol):
    def reachable(self, url: str, *, timeout_sec: float) -> bool:
        """Can the host named by ``url`` be connected to right now?"""
        ...


class SecretsPort(Protocol):
    def resolve(self, reference: str, *, timeout_sec: int) -> str:
        """The secret value, or raise SecretUnavailable."""
        ...


class NotifierPort(Protocol):
    def alert(self, *, title: str, text: str) -> None:
        """Raise a desktop notification; text is data, never script."""
        ...
