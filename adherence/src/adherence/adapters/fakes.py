"""adapters/fakes.py -- an in-memory adapter per port, for tests only.

container.py never imports this module; a test passes these in. Each
deadline-bound fake is scriptable to answer TimedOut.
"""

from __future__ import annotations

from collections.abc import Mapping

from adherence.domain.deadline import Deadline, TimedOut
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
