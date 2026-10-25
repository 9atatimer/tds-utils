"""adapters/fakes.py -- an in-memory adapter per port, for tests only.

container.py never imports this module; a test passes these in.
"""

from __future__ import annotations

from collections.abc import Mapping

from adherence.domain.deadline import Deadline
from adherence.domain.target import Base, Head
from adherence.ports.repository import Absent


class FakeRepository:
    """RepositoryPort over a mapping of target -> path -> bytes."""

    def __init__(self, files: Mapping[Base | Head, Mapping[str, bytes]]) -> None:
        self._files = files

    def read(
        self, path: str, at: Base | Head, deadline: Deadline | None
    ) -> bytes | Absent:
        found = self._files.get(at, {}).get(path)
        return Absent(path) if found is None else found
