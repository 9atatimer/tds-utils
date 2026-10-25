"""adapters/python_ast.py -- CodeModelPort for Python.

Facts come from the standard library `ast` over the bytes the use case
handed over; nothing in the sources is imported or run (ARCHITECTURE.
ARCH-ADHERENCE.md, Security mitigations). A source that does not parse is
Unparsed, for the use case to report as coverage.
"""

from __future__ import annotations

import ast
import time
from collections.abc import Mapping, Sequence

from adherence.adapters.python_imports import ImportGraphFailed, import_edges
from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import Declaration, layer_of, marker_regions
from adherence.domain.model import CodeModel, Region, Unit, UnitKind, Unparsed
from adherence.domain.parameters import Vocabulary

# --- Constants ---------------------------------------------------------------

DEFINITIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

# --- Helpers -----------------------------------------------------------------


def _passed(deadline: Deadline | None) -> bool:
    return deadline is not None and deadline.epoch_seconds <= time.time()


def _parse(path: str, data: bytes) -> ast.Module | Unparsed:
    try:
        return ast.parse(data, filename=path)
    except (SyntaxError, ValueError, RecursionError) as error:
        return Unparsed(path, f"not Python: {error}")


def _definitions(
    tree: ast.AST, scope: str | None = None
) -> list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef]]:
    """Every definition under a node, with its qualified symbol, in order."""
    found: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef]] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, DEFINITIONS):
            symbol = f"{scope}.{node.name}" if scope else node.name
            found.append((symbol, node))
            found.extend(_definitions(node, symbol))
        else:
            found.extend(_definitions(node, scope))
    return found


def _units(
    path: str,
    tree: ast.Module,
    lines: int,
    declaration: Declaration,
    regions: Sequence[Region],
) -> list[Unit]:
    units = [
        Unit(path, UnitKind.FILE, None, 1, lines, layer_of(path, None, declaration))
    ]
    for symbol, node in _definitions(tree):
        kind = UnitKind.TYPE if isinstance(node, ast.ClassDef) else UnitKind.FUNCTION
        end = node.end_lineno or node.lineno
        layer = layer_of(path, node.lineno, declaration, regions)
        units.append(Unit(path, kind, symbol, node.lineno, end, layer))
    return units


# --- Adapter -----------------------------------------------------------------


class PythonCodeModel:
    """CodeModelPort over Python sources."""

    def model(
        self,
        sources: Mapping[str, bytes],
        declaration: Declaration,
        vocabulary: Vocabulary,
        deadline: Deadline | None,
    ) -> CodeModel | TimedOut:
        if _passed(deadline):
            return TimedOut("model the Python sources")
        regions = tuple(
            region
            for path in declaration.layers.marker_files
            if path in sources
            for region in marker_regions(
                path, sources[path].decode("utf-8", "replace"), vocabulary
            )
        )
        units: list[Unit] = []
        unparsed: list[Unparsed] = []
        trees: dict[str, ast.Module] = {}
        for path in sorted(sources):
            tree = _parse(path, sources[path])
            if isinstance(tree, Unparsed):
                unparsed.append(tree)
                continue
            trees[path] = tree
            lines = sources[path].count(b"\n") or 1
            units.extend(_units(path, tree, lines, declaration, regions))
        try:
            imports = import_edges(sources, trees, deadline)
        except ImportGraphFailed as failure:
            if failure.timed_out:
                return TimedOut(str(failure))
            imports = []
            unparsed.extend(Unparsed(path, str(failure)) for path in trees)
        return CodeModel(
            units=tuple(units),
            imports=tuple(imports),
            regions=regions,
            unparsed=tuple(unparsed),
        )
