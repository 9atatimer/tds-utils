"""ports/duplication.py -- DuplicationPort: clones across the sources.

jscpd and a fake (ARCHITECTURE.ARCH-ADHERENCE.md, Seams); replaceable
without touching complexity. The use case hands over the sources' bytes
by repository path.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.model import Metrics


class DuplicationPort(Protocol):
    def measure(
        self, sources: Mapping[str, bytes], deadline: Deadline | None
    ) -> Metrics | TimedOut:
        """Every clone across the sources."""
        ...
