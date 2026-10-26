"""Build CodeModel facts by hand for the checks' tests: functions with their
signatures, types with their fields and methods, in the paths of the
measure kit's hexagon declaration."""

from __future__ import annotations

from adherence.domain.model import (
    Body,
    CodeModel,
    Definition,
    Member,
    MemberKind,
    Parameter,
    Signature,
    Unit,
    UnitKind,
)

RULES = "src/app/domain/rules.py"
USE = "src/app/application/use.py"
STORE = "src/app/ports/store.py"
FS = "src/app/adapters/fs.py"
ROOT = "src/app/container.py"
TEST = "tests/test_use.py"


def value(name: str, annotation: str | None = None) -> Parameter:
    """A positional parameter."""
    return Parameter(name, annotation, keyword_only=False, has_default=False)


def keyword(name: str, annotation: str | None = None) -> Parameter:
    """A keyword-only parameter."""
    return Parameter(name, annotation, keyword_only=True, has_default=False)


def function(
    path: str,
    symbol: str,
    line: int,
    parameters: tuple[Parameter, ...] = (),
    *,
    returns: str | None = None,
    parent: str | None = None,
    nested: bool = False,
    end: int | None = None,
) -> Definition:
    """A function or method definition at one line (or lines to end)."""
    unit = Unit(path, UnitKind.FUNCTION, symbol, line, end or line, None)
    return Definition(
        unit,
        Signature(parameters, returns),
        Body("return 1", (), ()),
        (),
        (),
        parent,
        nested,
    )


def type_(
    path: str,
    symbol: str,
    line: int,
    *,
    end: int | None = None,
    bases: tuple[str, ...] = (),
    parent: str | None = None,
    nested: bool = False,
) -> Definition:
    """A type definition from one line to end (default: two lines on)."""
    unit = Unit(path, UnitKind.TYPE, symbol, line, end or line + 2, None)
    return Definition(unit, None, Body("", (), ()), bases, (), parent, nested)


def port(path: str, name: str, line: int, method: str = "save") -> list[Definition]:
    """A Protocol port with one declared (stub) method."""
    unit = Unit(path, UnitKind.FUNCTION, f"{name}.{method}", line + 1, line + 1, None)
    declared = Definition(
        unit, Signature((), None), Body("...", ("...",), ()), (), (), name, False
    )
    return [type_(path, name, line, bases=("Protocol",)), declared]


def field(path: str, owner: str, name: str, line: int) -> Member:
    return Member(path, owner, name, MemberKind.FIELD, line)


def method(path: str, owner: str, name: str, line: int) -> Member:
    return Member(path, owner, name, MemberKind.METHOD, line)


def facts(
    definitions: list[Definition] | tuple[Definition, ...], **more: object
) -> CodeModel:
    """A CodeModel holding the definitions and their units, plus any other
    facts by keyword."""
    return CodeModel(
        units=tuple(d.unit for d in definitions),
        definitions=tuple(definitions),
        **more,
    )
