"""domain/model.py -- the CodeModel: the language-neutral facts every check reads.

Every analyzer produces one CodeModel; every check reads only that
(ARCHITECTURE.ARCH-ADHERENCE.md, Module map and Key Decisions).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

# --- Values ------------------------------------------------------------------


class CodeLanguage(enum.Enum):
    """A language the suite measures; named so it never collides with the
    Language check (ARCHITECTURE.ARCH-ADHERENCE.md, Use-case surface)."""

    PYTHON = "python"


class Layer(enum.Enum):
    """The closed layer set (DESIGN.ARCH-ADHERENCE.md, Units and layers)."""

    DOMAIN = "domain"
    APPLICATION = "application"
    PORTS = "ports"
    ADAPTERS = "adapters"
    COMPOSITION_ROOT = "composition root"
    TEST = "test"


@dataclass(frozen=True, slots=True)
class Region:
    """A span of one file, lines start to end inclusive, assigned to one layer."""

    path: str
    start: int
    end: int
    layer: Layer

    def holds(self, path: str, line: int) -> bool:
        """Whether the line of that file falls inside this region."""
        return path == self.path and self.start <= line <= self.end


class UnitKind(enum.Enum):
    """What a code unit is over."""

    FILE = "file"
    FUNCTION = "function"
    TYPE = "type"


@dataclass(frozen=True, slots=True)
class Unit:
    """What a check is over: a file, or a function or type in it, with its
    qualified symbol (None for a file), its lines and its layer (None when
    the declaration does not cover it)."""

    path: str
    kind: UnitKind
    symbol: str | None
    start: int
    end: int
    layer: Layer | None


@dataclass(frozen=True, slots=True)
class ImportEdge:
    """One import: the importing file, the module it resolves to, the line
    and its text, and the imported module's file when it is a source."""

    path: str
    imported: str
    line: int
    text: str
    imported_path: str | None


@dataclass(frozen=True, slots=True)
class Unparsed:
    """A source the analyzer could not read as its language, with the reason."""

    path: str
    reason: str


@dataclass(frozen=True, slots=True)
class CodeModel:
    """Every fact an analyzer read from the sources."""

    units: tuple[Unit, ...] = ()
    imports: tuple[ImportEdge, ...] = ()
    regions: tuple[Region, ...] = ()
    unparsed: tuple[Unparsed, ...] = ()
