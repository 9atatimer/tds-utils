"""Time and ids: injected so every use case is deterministic under test."""

from typing import Protocol


class Clock(Protocol):
    def now_ms(self) -> int:
        """Milliseconds since the Unix epoch, UTC."""
        ...


class IdSource(Protocol):
    def new_id(self, kind: str) -> str:
        """A fresh contract ``Id`` for a ``kind`` of record ("job", "batch"...).

        Never returned twice by one source.
        """
        ...
