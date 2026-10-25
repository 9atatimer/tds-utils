"""domain/declaration.py -- a repository's Declaration, parsed and validated.

The one owner of what a declaration says (ARCHITECTURE.ARCH-ADHERENCE.md,
Module map). Values in, values out: the bytes arrive from RepositoryPort
through the use case.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

# --- Constants ---------------------------------------------------------------

DECLARATION_PATH = "adherence.toml"

# --- Values ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Declaration:
    """A repository's statement of its layers, runtimes, records, radar and
    exemptions. Declaration.none is the value for a repository that has none.
    """

    declared: bool = True

    none: ClassVar[Declaration]


Declaration.none = Declaration(declared=False)

# --- Pure helpers ------------------------------------------------------------


def parse_declaration(text: bytes) -> Declaration:
    """The Declaration that adherence.toml's bytes state."""
    return Declaration()
