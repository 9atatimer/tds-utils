"""domain/records.py -- the design records of the code under measurement.

Read at the revision of the code they are compared against, never copied
(DESIGN.ARCH-ADHERENCE.md, Design records as input). So far the seam list
of the architecture record, which Change reads.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

# --- Values ------------------------------------------------------------------


class SeamKind(enum.Enum):
    """What an axis of change is mapped to."""

    PORT = "port"
    POLICY = "policy"
    PARAMETER = "parameter"


@dataclass(frozen=True, slots=True)
class Seam:
    """One seam the architecture record names, and where it names it."""

    name: str
    kind: SeamKind
    path: str
    line: int


@dataclass(frozen=True, slots=True)
class DesignRecords:
    """What the approved records state: their seams."""

    seams: tuple[Seam, ...] = ()


@dataclass(frozen=True, slots=True)
class RecordsUnavailable:
    """No readable record at the target -- absent, in draft, or not read --
    with the reason, naming the record."""

    reason: str
