"""domain/checks/roles.py -- the role a definition plays, read from the CodeModel.

What the Domain-driven, Composable and Injectable checks share: which
functions are use cases, which types are ports and concrete adapters, and
which names an annotation carries (the coding skill, Section 1.7,
Function taxonomy).
"""

from __future__ import annotations

import builtins
import enum
import re
from collections.abc import Mapping, Sequence

from adherence.domain.checks.hexagonal import implements, is_port
from adherence.domain.model import CodeModel, Definition, Layer, Parameter, UnitKind

# --- Constants ---------------------------------------------------------------

# A dotted name inside an annotation's text (`Mapping[str, tool.Store]`).
ANNOTATION_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
# A subscripted name inside an annotation's text (`typing.Literal[`).
SUBSCRIPTED = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s*\["
)
# The subscripts whose arguments are values, not types: a literal's
# contents, and an annotation's metadata after its first argument.
LITERAL = "Literal"
ANNOTATED = "Annotated"
QUOTES = frozenset("\"'")
PRIVATE = "_"
# The method that makes an instance of a class callable as a function.
CALL = "__call__"
# The method a value with no behaviour of its own may still carry.
INIT = "__init__"
# The bases, by name, that make a type an exception or an enum.
EXCEPTION_ROOTS = frozenset(
    name
    for name, kind in vars(builtins).items()
    if isinstance(kind, type) and issubclass(kind, BaseException)
)
ENUM_ROOTS = frozenset(
    name
    for name, kind in vars(enum).items()
    if isinstance(kind, type) and issubclass(kind, enum.Enum)
)

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


def _is_entry_type(definition: Definition | None) -> bool:
    """Whether a definition is a public type at the top level of an
    application unit, whose __call__ is a use case."""
    return (
        definition is not None
        and definition.unit.kind is UnitKind.TYPE
        and definition.unit.layer is Layer.APPLICATION
        and definition.parent is None
        and not definition.nested
        and not short_name(definition.unit.symbol).startswith(PRIVATE)
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


def _closing(text: str, opening: int) -> int:
    """The index of the bracket closing the one at `opening`, skipping
    quoted text; the text's length when it is never closed."""
    depth = 0
    quote: str | None = None
    for index in range(opening, len(text)):
        ch = text[index]
        if quote is not None:
            quote = None if ch == quote else quote
        elif ch in QUOTES:
            quote = ch
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return index
    return len(text)


def _first_argument_end(text: str, start: int, end: int) -> int:
    """The index ending a subscript's first argument: its first top-level
    comma between start and end, or end."""
    depth = 0
    quote: str | None = None
    for index in range(start, end):
        ch = text[index]
        if quote is not None:
            quote = None if ch == quote else quote
        elif ch in QUOTES:
            quote = ch
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        elif ch == "," and depth == 0:
            return index
    return end


def type_text(annotation: str) -> str:
    """An annotation's text with every value in it removed: a literal's
    contents (`Literal["fast"]` -> `Literal`) and an annotation's metadata
    (`Annotated[Order, "memo"]` -> `Annotated[Order]`). A quoted forward
    reference elsewhere is a type's name and stays."""
    kept: list[str] = []
    at = 0
    while (match := SUBSCRIPTED.search(annotation, at)) is not None:
        name = short_name(match.group(1))
        if name not in (LITERAL, ANNOTATED):
            kept.append(annotation[at : match.end()])
            at = match.end()
            continue
        opening = match.end() - 1
        closing = _closing(annotation, opening)
        kept.append(annotation[at : match.end(1)])
        if name == ANNOTATED:
            first = _first_argument_end(annotation, opening + 1, closing)
            kept.append(f"[{type_text(annotation[opening + 1 : first])}]")
        at = closing + 1
    kept.append(annotation[at:])
    return "".join(kept)


def annotation_names(annotation: str | None) -> tuple[str, ...]:
    """Every dotted name an annotation's text carries, in order: the names
    of types, never a literal's contents or an annotation's metadata."""
    return tuple(ANNOTATION_NAME.findall(type_text(annotation or "")))


def module_bindings(model: CodeModel) -> Mapping[tuple[str, str], str]:
    """Every module-level binding, keyed by its path and the name bound."""
    return {(b.path, b.name): b.value for b in model.bindings if b.within is None}


def resolved(name: str, path: str, bindings: Mapping[tuple[str, str], str]) -> str:
    """A dotted name as written in a file, with its first part replaced by
    what that part is bound to at module level, through every alias of an
    alias, until it names nothing bound or comes back round."""
    seen: set[str] = set()
    while True:
        head, dot, rest = name.partition(".")
        target = bindings.get((path, head))
        if target is None or head in seen:
            return name
        seen.add(head)
        name = f"{target}{dot}{rest}"


def use_cases(model: CodeModel) -> list[Definition]:
    """Every use case the model defines, in order: a public top-level
    application function, a private one a module-level binding exports
    under a public name (`hidden = _hidden`), and the __call__ of a public
    top-level application class."""
    exported = {
        (b.path, b.value)
        for b in model.bindings
        if b.within is None and not b.name.startswith(PRIVATE)
    }
    definitions = by_symbol(model)
    found: list[Definition] = []
    for d in model.definitions:
        unit = d.unit
        if unit.kind is not UnitKind.FUNCTION or unit.layer is not Layer.APPLICATION:
            continue
        if d.nested:
            continue
        if d.parent is None:
            if is_use_case(d) or (unit.path, unit.symbol or "") in exported:
                found.append(d)
        elif short_name(unit.symbol) == CALL and _is_entry_type(
            definitions.get((unit.path, d.parent))
        ):
            found.append(d)
    return found


def _methods(model: CodeModel) -> dict[tuple[str, str], list[Definition]]:
    """Each type's methods, keyed by the type's path and symbol."""
    methods: dict[tuple[str, str], list[Definition]] = {}
    for d in model.definitions:
        if d.unit.kind is UnitKind.FUNCTION and d.parent is not None:
            methods.setdefault((d.unit.path, d.parent), []).append(d)
    return methods


def port_names(model: CodeModel) -> frozenset[str]:
    """The names of every port the model defines."""
    methods = _methods(model)
    return frozenset(
        short_name(d.unit.symbol)
        for d in model.definitions
        if d.unit.kind is UnitKind.TYPE
        and is_port(d, methods.get((d.unit.path, d.unit.symbol or ""), []))
    )


def named_in(parameter: Parameter, names: frozenset[str]) -> str | None:
    """The first name the parameter's annotation carries, by its last part,
    that is one of `names`; None if it carries none."""
    return next(
        (n for n in annotation_names(parameter.annotation) if short_name(n) in names),
        None,
    )


def _descends_from(
    definition: Definition,
    roots: frozenset[str],
    types: Mapping[str, Sequence[Definition]],
) -> bool:
    """Whether a type names one of `roots` as a base, by its last part,
    directly or through a type the model defines, by name."""
    seen: set[str] = set()
    pending = list(definition.bases)
    while pending:
        base = short_name(pending.pop())
        if base in roots:
            return True
        if base in seen:
            continue
        seen.add(base)
        pending.extend(b for t in types.get(base, ()) for b in t.bases)
    return False


def _is_value(methods: Sequence[Definition]) -> bool:
    """Whether a type is all fields: no method beyond __init__."""
    return all(short_name(m.unit.symbol) == INIT for m in methods)


def adapter_names(model: CodeModel) -> frozenset[str]:
    """The names of every concrete adapter the model defines: a type in the
    adapters layer, whatever its name, that implements a port or, port or
    no port, is no exception, enum or value (all fields, no method beyond
    __init__). A fake's name exempts it only from what the design says
    (Swap counts it); a use case wiring it is still wiring an adapter."""
    methods = _methods(model)
    types = [d for d in model.definitions if d.unit.kind is UnitKind.TYPE]
    named: dict[str, list[Definition]] = {}
    for t in types:
        named.setdefault(short_name(t.unit.symbol), []).append(t)
    ports = [(p, methods.get((p.unit.path, p.unit.symbol or ""), [])) for p in types]
    ports = [(p, own) for p, own in ports if is_port(p, own)]
    found: set[str] = set()
    for t in types:
        if t.unit.layer is not Layer.ADAPTERS:
            continue
        own = methods.get((t.unit.path, t.unit.symbol or ""), [])
        if any(implements(t, own, p, theirs) for p, theirs in ports):
            found.add(short_name(t.unit.symbol))
        elif not (
            _is_value(own)
            or _descends_from(t, EXCEPTION_ROOTS, named)
            or _descends_from(t, ENUM_ROOTS, named)
        ):
            found.add(short_name(t.unit.symbol))
    return frozenset(found)
