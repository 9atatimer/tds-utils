"""domain/checks/roles.py -- the role a definition plays, read from the CodeModel.

What the Domain-driven, Composable and Injectable checks share: which
functions are use cases, which types are ports and concrete adapters, and
which names an annotation carries (the coding skill, Section 1.7,
Function taxonomy).
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from adherence.domain.model import CodeModel, Definition, Layer, UnitKind

# --- Constants ---------------------------------------------------------------

# A dotted name inside an annotation's text (`Mapping[str, tool.Store]`).
ANNOTATION_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
PRIVATE = "_"

# --- Predicates --------------------------------------------------------------


def is_use_case(definition: Definition) -> bool:
    """Whether a definition is a use case: a public function at the top
    level of an application unit."""
    unit = definition.unit
    return (
        unit.kind is UnitKind.FUNCTION
        and unit.layer is Layer.APPLICATION
        and definition.parent is None
        and not definition.nested
        and not short_name(unit.symbol).startswith(PRIVATE)
    )


def is_within(within: str | None, symbol: str | None) -> bool:
    """Whether a fact sitting in `within` sits in the definition `symbol`,
    or in a definition nested in it."""
    if within is None or symbol is None:
        return False
    return within == symbol or within.startswith(f"{symbol}.")


# --- Pure helpers ------------------------------------------------------------


def short_name(symbol: str | None) -> str:
    """A qualified symbol's last part."""
    return (symbol or "").rpartition(".")[2]


def by_symbol(model: CodeModel) -> Mapping[tuple[str, str], Definition]:
    """Every definition, keyed by its path and qualified symbol."""
    return {(d.unit.path, d.unit.symbol or ""): d for d in model.definitions}


def enclosing_function(
    definition: Definition, definitions: Mapping[tuple[str, str], Definition]
) -> Definition | None:
    """The nearest function a definition is defined inside, walking out
    through the types between them."""
    parent = definition.parent
    while parent is not None:
        outer = definitions.get((definition.unit.path, parent))
        if outer is None:
            return None
        if outer.unit.kind is UnitKind.FUNCTION:
            return outer
        parent = outer.parent
    return None


def annotation_names(annotation: str | None) -> tuple[str, ...]:
    """Every dotted name an annotation's text carries, in order."""
    return tuple(ANNOTATION_NAME.findall(annotation or ""))
