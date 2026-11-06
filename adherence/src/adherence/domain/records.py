"""domain/records.py -- the design records of the code under measurement.

Read at the revision of the code they are compared against, never copied
(DESIGN.ARCH-ADHERENCE.md, Design records as input): the design's
Behaviors table and Domain Language, the architecture record's use-case
surface with the signatures it gives, and its seam list. Change reads the
seams; Language reads the Domain Language.
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
    """One term the design's Domain Language defines, under its spelling,
    and where the record defines it."""

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
    """What the merged records state: their seams, behaviors, the design's
    Domain Language, the use cases the surface gives a signature, and the
    surface's rows. A record counts by being present at the revision
    measured: merged is the approval, so whatever status-like line it
    carries is not read (design skill, Lifecycle is metadata)."""

    seams: tuple[Seam, ...] = ()
    behaviors: tuple[Behavior, ...] = ()
    domain_language: tuple[Term, ...] = ()
    use_cases: tuple[UseCase, ...] = ()
    surface: tuple[SurfaceRow, ...] = ()


@dataclass(frozen=True, slots=True)
class RecordsUnavailable:
    """No readable record at the target -- absent or not read -- with the
    reason, naming the record. The frozen DESIGN.ARCH-ADHERENCE.md row "A
    missing design record is reported" says "absent or in draft": a draft is
    an unmerged PR, so at the revision measured it is absent, never present
    with a DRAFT line (design skill, Lifecycle is metadata: merged is the
    approval). `unread` marks a record that is there and could not be read
    (refused, timed out): what it states is unknown, which is never the
    same as a record stating nothing."""

    reason: str
    unread: bool = False


class Ring(enum.Enum):
    """A radar's rings; only Adopt and Trial may be introduced."""

    ADOPT = "Adopt"
    TRIAL = "Trial"
    ASSESS = "Assess"
    HOLD = "Hold"
    VERBOTEN = "Verboten"


@dataclass(frozen=True, slots=True)
class RadarEntry:
    """One technology the radar names, its ring, and where it names it."""

    name: str
    ring: Ring
    path: str
    line: int


@dataclass(frozen=True, slots=True)
class Radar:
    """The tech radar the declaration names, read for its rings."""

    entries: tuple[RadarEntry, ...] = ()
