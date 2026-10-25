"""adapters/fakes.py -- an in-memory adapter per port, for tests only.

container.py never imports this module; a test passes these in. Each
deadline-bound fake is scriptable to answer TimedOut.
"""

from __future__ import annotations

from collections.abc import Mapping

from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import Declaration, layer_of
from adherence.domain.model import CodeModel, Unit, UnitKind
from adherence.domain.parameters import Vocabulary
from adherence.domain.target import Base, Head
from adherence.ports.repository import Absent, Refused


class FakeRepository:
    """RepositoryPort over a mapping of target -> path -> answer: the bytes,
    or the Refused or TimedOut the test scripts for that path."""

    def __init__(
        self, files: Mapping[Base | Head, Mapping[str, bytes | Refused | TimedOut]]
    ) -> None:
        self._files = files

    def read(
        self, path: str, at: Base | Head, deadline: Deadline | None
    ) -> bytes | Absent | Refused | TimedOut:
        found = self._files.get(at, {}).get(path)
        return Absent(path) if found is None else found

    def tree(
        self, at: Base | Head, deadline: Deadline | None
    ) -> tuple[str, ...] | TimedOut:
        return tuple(sorted(self._files.get(at, {})))


class FakeCodeModel:
    """CodeModelPort over units the test configures: a file unit per source,
    plus the configured units of those files, each re-layered by the
    declaration. Its clock is frozen at `now`, so a deadline at or before it
    has passed."""

    def __init__(self, units: tuple[Unit, ...] = (), *, now: float = 1e9) -> None:
        self._units = units
        self._now = now

    def model(
        self,
        sources: Mapping[str, bytes],
        declaration: Declaration,
        vocabulary: Vocabulary,
        deadline: Deadline | None,
    ) -> CodeModel | TimedOut:
        if deadline is not None and deadline.epoch_seconds <= self._now:
            return TimedOut("model the sources")
        files = tuple(
            Unit(path, UnitKind.FILE, None, 1, 1, layer_of(path, None, declaration))
            for path in sorted(sources)
        )
        defined = tuple(
            Unit(
                u.path,
                u.kind,
                u.symbol,
                u.start,
                u.end,
                layer_of(u.path, u.start, declaration),
            )
            for u in self._units
            if u.path in sources
        )
        return CodeModel(units=files + defined)
