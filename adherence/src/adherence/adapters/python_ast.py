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
    Access,
    AccessKind,
    Body,
    Call,
    CodeModel,
    Conditional,
    Definition,
    Member,
    MemberKind,
    Parameter,
    Reference,
    ReferenceKind,
    Region,
    Signature,
    TestCase,
    Unit,
    UnitKind,
    Unparsed,
    Write,
)
from adherence.domain.parameters import Vocabulary

# --- Constants ---------------------------------------------------------------

DEFINITIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
SLEEP = "sleep"
# Python's ways to read the process environment.
ENVIRONMENT_READS = frozenset({"os.environ", "os.getenv", "environ", "getenv"})

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


def own_nodes(node: ast.AST) -> list[ast.AST]:
    """Every node inside a definition, not descending into the definitions
    nested in it, which are their own units."""
    found: list[ast.AST] = []
    for child in ast.iter_child_nodes(node):
        found.append(child)
        if not isinstance(child, DEFINITIONS):
            found.extend(own_nodes(child))
    return found


def _statements(node: DefinitionNode) -> list[ast.stmt]:
    """The body's statements without a leading docstring."""
    body = list(node.body)
    first = body[0] if body else None
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        body = body[1:]
    return body


def _stub_markers(node: DefinitionNode) -> tuple[str, ...]:
    statements = _statements(node)
    if len(statements) != 1:
        return ()
    only = statements[0]
    if isinstance(only, ast.Pass):
        return ("pass",)
    if isinstance(only, ast.Expr) and isinstance(only.value, ast.Constant):
        if only.value.value is Ellipsis:
            return ("...",)
    if isinstance(only, ast.Raise) and only.exc is not None:
        raised = only.exc.func if isinstance(only.exc, ast.Call) else only.exc
        if isinstance(raised, ast.Name) and raised.id == "NotImplementedError":
            return ("NotImplementedError",)
    return ()


def _callee(call: ast.Call) -> str:
    return ast.unparse(call.func)


def _body(node: DefinitionNode, text: str) -> Body:
    statements = node.body
    first, last = statements[0], statements[-1]
    lines = text.splitlines()[first.lineno - 1 : (last.end_lineno or last.lineno)]
    sleeps = sorted(
        {
            n.lineno
            for n in own_nodes(node)
            if isinstance(n, ast.Call) and _callee(n).split(".")[-1] == SLEEP
        }
    )
    return Body("\n".join(lines), _stub_markers(node), tuple(sleeps))


def _definition(
    path: str,
    found: _Found,
    text: str,
    declaration: Declaration,
    regions: Sequence[Region],
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
        body=_body(node, text),
        bases=tuple(ast.unparse(b) for b in node.bases)
        if isinstance(node, ast.ClassDef)
        else (),
        decorators=tuple(ast.unparse(d) for d in node.decorator_list),
        parent=found.parent,
        nested=found.nested,
    )


def _scoped(
    tree: ast.Module, found: Sequence[_Found]
) -> list[tuple[str | None, ast.AST]]:
    """Every node of a file with the symbol of the definition it sits in."""
    nodes: list[tuple[str | None, ast.AST]] = [(None, n) for n in own_nodes(tree)]
    for f in found:
        nodes.extend((f.symbol, n) for n in own_nodes(f.node))
    return nodes


def _docstrings(tree: ast.Module) -> set[int]:
    """The ids of every docstring constant in a file."""
    owners = [tree, *(n for n in ast.walk(tree) if isinstance(n, DEFINITIONS))]
    found: set[int] = set()
    for owner in owners:
        first = owner.body[0] if owner.body else None
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
            found.add(id(first.value))
    return found


def _chain(node: ast.expr) -> bool:
    """Whether an expression is a dotted chain of names (os.environ.get)."""
    while isinstance(node, ast.Attribute):
        node = node.value
    return isinstance(node, ast.Name)


def _references(
    path: str, tree: ast.Module, scoped: Sequence[tuple[str | None, ast.AST]]
) -> list[Reference]:
    docstrings = _docstrings(tree)
    inner = {
        id(n.value) for _, n in scoped if isinstance(n, ast.Attribute) and _chain(n)
    }
    found: list[Reference] = []
    for within, node in scoped:
        if id(node) in inner:
            continue
        if isinstance(node, ast.Attribute) and _chain(node):
            text, kind = ast.unparse(node), ReferenceKind.NAME
        elif isinstance(node, ast.Name):
            text, kind = node.id, ReferenceKind.NAME
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ):
            text, kind = node.value, ReferenceKind.STRING
        else:
            continue
        found.append(Reference(path, node.lineno, within, kind, text))
    return found


def _calls(path: str, scoped: Sequence[tuple[str | None, ast.AST]]) -> list[Call]:
    return [
        Call(path, node.lineno, within, _callee(node))
        for within, node in scoped
        if isinstance(node, ast.Call)
    ]


def _accesses(path: str, scoped: Sequence[tuple[str | None, ast.AST]]) -> list[Access]:
    inner = {
        id(n.value) for _, n in scoped if isinstance(n, ast.Attribute) and _chain(n)
    }
    found: list[Access] = []
    for within, node in scoped:
        if isinstance(node, ast.Global):
            found.extend(
                Access(path, node.lineno, within, AccessKind.GLOBAL, name)
                for name in node.names
            )
        elif isinstance(node, ast.Attribute | ast.Name) and id(node) not in inner:
            text = ast.unparse(node)
            if text in ENVIRONMENT_READS:
                found.append(
                    Access(path, node.lineno, within, AccessKind.ENVIRONMENT, text)
                )
    return found


def _assigned(node: ast.AST) -> list[ast.expr]:
    if isinstance(node, ast.Assign):
        return list(node.targets)
    if isinstance(node, ast.AugAssign | ast.AnnAssign):
        return [node.target]
    return []


def _writes(path: str, scoped: Sequence[tuple[str | None, ast.AST]]) -> list[Write]:
    return [
        Write(path, target.lineno, within, ast.unparse(target.value), target.attr)
        for within, node in scoped
        for target in _assigned(node)
        if isinstance(target, ast.Attribute)
    ]


def _discriminants(test: ast.expr) -> list[str]:
    """What a branch's test discriminates on: the left of a comparison, the
    value an isinstance tests, each operand of a bool op, a bare name."""
    if isinstance(test, ast.BoolOp):
        return [d for value in test.values for d in _discriminants(value)]
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return _discriminants(test.operand)
    if isinstance(test, ast.Compare):
        return [ast.unparse(test.left)]
    if isinstance(test, ast.Call):
        if _callee(test) == "isinstance" and test.args:
            return [ast.unparse(test.args[0])]
        return [_callee(test)]
    return [ast.unparse(test)]


def _conditionals(
    path: str, scoped: Sequence[tuple[str | None, ast.AST]]
) -> list[Conditional]:
    found: list[Conditional] = []
    for within, node in scoped:
        if isinstance(node, ast.If | ast.While | ast.IfExp):
            tests = _discriminants(node.test)
        elif isinstance(node, ast.Match):
            tests = [ast.unparse(node.subject)]
        else:
            continue
        found.extend(Conditional(path, node.lineno, within, t) for t in tests)
    return found


SELF = "self"


def _self_fields(method: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.Attribute]:
    """The `self.<field> = ...` targets in a method."""
    return [
        target
        for node in own_nodes(method)
        for target in _assigned(node)
        if isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == SELF
    ]


def _type_members(path: str, found: _Found) -> list[Member]:
    """One type's declared fields, methods and self-assigned fields, in order."""
    members: list[Member] = []
    for statement in found.node.body:
        if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef):
            members.append(
                Member(
                    path,
                    found.symbol,
                    statement.name,
                    MemberKind.METHOD,
                    statement.lineno,
                )
            )
            members.extend(
                Member(path, found.symbol, t.attr, MemberKind.FIELD, t.lineno)
                for t in _self_fields(statement)
            )
        else:
            members.extend(
                Member(path, found.symbol, t.id, MemberKind.FIELD, t.lineno)
                for t in _assigned(statement)
                if isinstance(t, ast.Name)
            )
    return members


def _members(path: str, walked: Sequence[_Found]) -> list[Member]:
    """Every type's members, each name once, at its first occurrence."""
    first: dict[tuple[str, str], Member] = {}
    for f in walked:
        if isinstance(f.node, ast.ClassDef):
            for member in _type_members(path, f):
                first.setdefault((member.owner, member.name), member)
    return list(first.values())


TEST_PREFIX = "test"
TEST_CLASS_PREFIX = "Test"


def is_test(found: _Found, classes: set[str]) -> bool:
    """Whether a definition is a test: a function named test* at module
    level, or a method named test* of a class named Test*."""
    if isinstance(found.node, ast.ClassDef) or not found.node.name.startswith(
        TEST_PREFIX
    ):
        return False
    if found.parent is None:
        return True
    return found.parent in classes and found.parent.split(".")[-1].startswith(
        TEST_CLASS_PREFIX
    )


def _test_cases(path: str, walked: Sequence[_Found]) -> list[TestCase]:
    classes = {f.symbol for f in walked if isinstance(f.node, ast.ClassDef)}
    cases: list[TestCase] = []
    for f in walked:
        if not is_test(f, classes):
            continue
        nodes = own_nodes(f.node)
        calls = tuple(_callee(n) for n in nodes if isinstance(n, ast.Call))
        asserts = tuple(ast.unparse(n.test) for n in nodes if isinstance(n, ast.Assert))
        cases.append(TestCase(path, f.symbol, f.node.lineno, calls, asserts))
    return cases


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
        references: list[Reference] = []
        calls: list[Call] = []
        accesses: list[Access] = []
        writes: list[Write] = []
        conditionals: list[Conditional] = []
        members: list[Member] = []
        test_cases: list[TestCase] = []
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
            text = sources[path].decode("utf-8", "replace")
            walked = _walk_definitions(tree)
            found = [_definition(path, f, text, declaration, regions) for f in walked]
            definitions.extend(found)
            units.extend(d.unit for d in found)
            scoped = _scoped(tree, walked)
            references.extend(_references(path, tree, scoped))
            calls.extend(_calls(path, scoped))
            accesses.extend(_accesses(path, scoped))
            writes.extend(_writes(path, scoped))
            conditionals.extend(_conditionals(path, scoped))
            members.extend(_members(path, walked))
            test_cases.extend(_test_cases(path, walked))
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
            references=tuple(references),
            calls=tuple(calls),
            accesses=tuple(accesses),
            writes=tuple(writes),
            conditionals=tuple(conditionals),
            members=tuple(members),
            test_cases=tuple(test_cases),
            regions=regions,
            unparsed=tuple(unparsed),
        )
