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
    TYPESCRIPT = "typescript"
    JAVASCRIPT = "javascript"
    SHELL = "shell"


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
class Parameter:
    """One parameter of a function: its name (`*args` and `**kwargs` keep
    their stars), its annotation's text, and how it is passed."""

    name: str
    annotation: str | None
    keyword_only: bool
    has_default: bool


@dataclass(frozen=True, slots=True)
class Signature:
    """A function's parameters, in order, and its return annotation's text."""

    parameters: tuple[Parameter, ...]
    returns: str | None


@dataclass(frozen=True, slots=True)
class Body:
    """A definition's body: its text, the placeholder it consists of when it
    is nothing but one (`pass`, `...`, `NotImplementedError`), and the lines
    where it sleeps. Nested definitions are their own bodies."""

    text: str
    stub_markers: tuple[str, ...]
    sleeps: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class Definition:
    """A function or type: its unit, its signature (None for a type), its
    body, its bases and decorators as written, the symbol it is defined in, and
    whether a function encloses it."""

    unit: Unit
    signature: Signature | None
    body: Body
    bases: tuple[str, ...]
    decorators: tuple[str, ...]
    parent: str | None
    nested: bool


@dataclass(frozen=True, slots=True)
class ImportEdge:
    """One import: the importing file, the module it resolves to, the line
    and its text, and the imported module's file when it is a source."""

    path: str
    imported: str
    line: int
    text: str
    imported_path: str | None


class ReferenceKind(enum.Enum):
    """A name (a dotted chain, as written) or a string literal."""

    NAME = "name"
    STRING = "string"


@dataclass(frozen=True, slots=True)
class Reference:
    """A name or string literal, the line it is on, and the symbol of the
    definition it sits in (None at module level)."""

    path: str
    line: int
    within: str | None
    kind: ReferenceKind
    text: str


@dataclass(frozen=True, slots=True)
class Call:
    """A function or constructor call: its callee as written, its line, and
    the definition it sits in."""

    path: str
    line: int
    within: str | None
    callee: str


class AccessKind(enum.Enum):
    """A read of the process environment, or of a declared global."""

    ENVIRONMENT = "environment"
    GLOBAL = "global"


@dataclass(frozen=True, slots=True)
class Access:
    """A read of the environment or a global: what is read, its line, and
    the definition it sits in."""

    path: str
    line: int
    within: str | None
    kind: AccessKind
    target: str


@dataclass(frozen=True, slots=True)
class Write:
    """An assignment to a field: the object written (as written), the
    field, its line, and the definition that makes it."""

    path: str
    line: int
    within: str | None
    target: str
    field: str


@dataclass(frozen=True, slots=True)
class Conditional:
    """A branch: the expression it discriminates on (as written), its line,
    and the definition it sits in. A branch on several is one per each."""

    path: str
    line: int
    within: str | None
    discriminant: str


class MemberKind(enum.Enum):
    """A field or a method of a type."""

    FIELD = "field"
    METHOD = "method"


@dataclass(frozen=True, slots=True)
class Member:
    """A field or method of a type: the type's symbol, the member's name,
    and the line it is first declared or assigned on."""

    path: str
    owner: str
    name: str
    kind: MemberKind
    line: int


@dataclass(frozen=True, slots=True)
class TestCase:
    """A test: its symbol, its line, the callees it calls, and the
    expressions it asserts, as written."""

    __test__ = False  # a domain value, not a pytest class

    path: str
    symbol: str
    line: int
    calls: tuple[str, ...]
    assertions: tuple[str, ...]


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
    definitions: tuple[Definition, ...] = ()
    references: tuple[Reference, ...] = ()
    calls: tuple[Call, ...] = ()
    accesses: tuple[Access, ...] = ()
    writes: tuple[Write, ...] = ()
    conditionals: tuple[Conditional, ...] = ()
    members: tuple[Member, ...] = ()
    test_cases: tuple[TestCase, ...] = ()
    regions: tuple[Region, ...] = ()
    unparsed: tuple[Unparsed, ...] = ()
