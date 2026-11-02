"""domain/records.py -- the design records of the code under measurement.

Read at the revision of the code they are compared against, never copied
(DESIGN.ARCH-ADHERENCE.md, Design records as input): the design's
Behaviors table and Domain Language, the architecture record's use-case
surface with the signatures it gives, and its seam list.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from adherence.domain.model import Signature

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
class Behavior:
    """One row of the design's Behaviors table: its name, its Given / When /
    Then as written, and where the record states it."""

    name: str
    scenario: str
    path: str
    line: int


@dataclass(frozen=True, slots=True)
class Term:
    """One term the design's Domain Language defines, by its spelling."""

    name: str
    path: str
    line: int


@dataclass(frozen=True, slots=True)
class UseCase:
    """A use case the architecture record's use-case surface gives a
    signature, and where it gives it."""

    name: str
    signature: Signature
    path: str
    line: int


@dataclass(frozen=True, slots=True)
class SurfaceRow:
    """One row of the use-case surface: the design behavior it carries and
    the use case it names, None when it names none."""

    behavior: str
    use_case: str | None
    path: str
    line: int


@dataclass(frozen=True, slots=True)
class DesignRecords:
    """What the approved records state: their seams, behaviors, terms, the
    use cases the surface gives a signature, and the surface's rows."""

    seams: tuple[Seam, ...] = ()
    behaviors: tuple[Behavior, ...] = ()
    terms: tuple[Term, ...] = ()
    use_cases: tuple[UseCase, ...] = ()
    surface: tuple[SurfaceRow, ...] = ()


@dataclass(frozen=True, slots=True)
class RecordsUnavailable:
    """No readable record at the target -- absent, in draft, or not read --
    with the reason, naming the record."""

    reason: str
