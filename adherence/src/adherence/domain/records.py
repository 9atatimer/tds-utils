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
class Behavior:
    """One row of a design record's Behaviors table, by its name, and where
    the record states it."""

    name: str
    path: str
    line: int


@dataclass(frozen=True, slots=True)
class UseCase:
    """One row of the architecture record's use-case surface: the design
    behavior and the application function that carries it."""

    behavior: str
    function: str
    path: str
    line: int


@dataclass(frozen=True, slots=True)
class DesignRecords:
    """What the approved records state: their seams, the design behaviors
    and the use-case surface."""

    seams: tuple[Seam, ...] = ()
    behaviors: tuple[Behavior, ...] = ()
    surface: tuple[UseCase, ...] = ()


@dataclass(frozen=True, slots=True)
class RecordsUnavailable:
    """No readable record at the target -- absent, in draft, or not read --
    with the reason, naming the record."""

    reason: str


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
