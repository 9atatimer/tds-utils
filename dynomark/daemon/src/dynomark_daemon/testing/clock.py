"""Fake Clock and IdSource: time moves only when a test says so."""


class FakeClock:
    """A ``Clock`` at ``start_ms`` that moves only on ``advance``."""

    def __init__(self, *, start_ms: int = 0) -> None:
        self._now_ms = start_ms

    def now_ms(self) -> int:
        return self._now_ms

    def advance(self, ms: int) -> None:
        if ms < 0:
            raise ValueError("a clock never goes backwards")
        self._now_ms += ms


class SequentialIds:
    """An ``IdSource`` yielding ``<kind>-<n>`` with one counter across kinds."""

    def __init__(self) -> None:
        self._issued = 0

    def new_id(self, kind: str) -> str:
        self._issued += 1
        return f"{kind}-{self._issued}"
