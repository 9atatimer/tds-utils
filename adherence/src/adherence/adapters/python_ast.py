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
from dataclasses import dataclass

from adherence.adapters.python_imports import ImportGraphFailed, import_edges
from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import Declaration, layer_of, marker_regions
from adherence.domain.model import (
    CodeModel,
    Definition,
    Parameter,
    Region,
    Signature,
    Unit,
    UnitKind,
    Unparsed,
)
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


DefinitionNode = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


@dataclass(frozen=True, slots=True)
class _Found:
    symbol: str
    node: DefinitionNode
    parent: str | None
    nested: bool


def _walk_definitions(
    tree: ast.AST, scope: str | None = None, in_function: bool = False
) -> list[_Found]:
    """Every definition under a node, with its qualified symbol, in order."""
    found: list[_Found] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, DEFINITIONS):
            symbol = f"{scope}.{node.name}" if scope else node.name
            found.append(_Found(symbol, node, scope, in_function))
            is_function = not isinstance(node, ast.ClassDef)
            found.extend(_walk_definitions(node, symbol, in_function or is_function))
        else:
            found.extend(_walk_definitions(node, scope, in_function))
    return found


def _text(node: ast.expr | None) -> str | None:
    return None if node is None else ast.unparse(node)


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> Signature:
    arguments = node.args
    positional = [*arguments.posonlyargs, *arguments.args]
    first_default = len(positional) - len(arguments.defaults)
    parameters = [
        Parameter(arg.arg, _text(arg.annotation), False, index >= first_default)
        for index, arg in enumerate(positional)
    ]
    if arguments.vararg is not None:
        vararg = arguments.vararg
        parameters.append(
            Parameter(f"*{vararg.arg}", _text(vararg.annotation), False, False)
        )
    parameters.extend(
        Parameter(arg.arg, _text(arg.annotation), True, default is not None)
        for arg, default in zip(
            arguments.kwonlyargs, arguments.kw_defaults, strict=True
        )
    )
    if arguments.kwarg is not None:
        kwarg = arguments.kwarg
        parameters.append(
            Parameter(f"**{kwarg.arg}", _text(kwarg.annotation), False, False)
        )
    return Signature(tuple(parameters), _text(node.returns))


def _definition(
    path: str, found: _Found, declaration: Declaration, regions: Sequence[Region]
) -> Definition:
    node = found.node
    is_type = isinstance(node, ast.ClassDef)
    unit = Unit(
        path,
        UnitKind.TYPE if is_type else UnitKind.FUNCTION,
        found.symbol,
        node.lineno,
        node.end_lineno or node.lineno,
        layer_of(path, node.lineno, declaration, regions),
    )
    return Definition(
        unit=unit,
        signature=None if isinstance(node, ast.ClassDef) else _signature(node),
        bases=tuple(ast.unparse(b) for b in node.bases)
        if isinstance(node, ast.ClassDef)
        else (),
        decorators=tuple(ast.unparse(d) for d in node.decorator_list),
        parent=found.parent,
        nested=found.nested,
    )


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
        definitions: list[Definition] = []
        unparsed: list[Unparsed] = []
        trees: dict[str, ast.Module] = {}
        for path in sorted(sources):
            tree = _parse(path, sources[path])
            if isinstance(tree, Unparsed):
                unparsed.append(tree)
                continue
            trees[path] = tree
            lines = sources[path].count(b"\n") or 1
            file_layer = layer_of(path, None, declaration)
            units.append(Unit(path, UnitKind.FILE, None, 1, lines, file_layer))
            found = [
                _definition(path, f, declaration, regions)
                for f in _walk_definitions(tree)
            ]
            definitions.extend(found)
            units.extend(d.unit for d in found)
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
            definitions=tuple(definitions),
            regions=regions,
            unparsed=tuple(unparsed),
        )
