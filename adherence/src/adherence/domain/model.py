"""domain/model.py -- the CodeModel: the language-neutral facts every check reads.

Every analyzer produces one CodeModel; every check reads only that
(ARCHITECTURE.ARCH-ADHERENCE.md, Module map and Key Decisions).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

# --- Values ------------------------------------------------------------------


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
