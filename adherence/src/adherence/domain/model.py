"""domain/model.py -- the CodeModel: the language-neutral facts every check reads.

Every analyzer produces one CodeModel; every check reads only that
(ARCHITECTURE.ARCH-ADHERENCE.md, Module map and Key Decisions).
"""

from __future__ import annotations

import enum
from collections.abc import Sequence
from dataclasses import dataclass

# --- Values ------------------------------------------------------------------


class CodeLanguage(enum.Enum):
    """A language the suite measures; named so it never collides with the
    Language check (ARCHITECTURE.ARCH-ADHERENCE.md, Use-case surface)."""

    PYTHON = "python"


# A source's language by its file extension: the languages the suite
# measures, and the others it recognises so it can say it does not.
LANGUAGE_EXTENSIONS: dict[str, str] = {
    ".py": CodeLanguage.PYTHON.value,
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".vue": "vue",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".go": "go",
    ".gd": "gdscript",
    ".rb": "ruby",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".swift": "swift",
    ".c": "c",
    ".h": "c",
    ".cc": "c++",
    ".cpp": "c++",
    ".el": "emacs lisp",
    ".lua": "lua",
    ".php": "php",
}


def language_of(path: str) -> str | None:
    """The language a source path is written in, by its extension; None
    when the path is not a source the suite knows."""
    name = path.rpartition("/")[2]
    stem, dot, extension = name.rpartition(".")
    if not dot or not stem:
        return None
    return LANGUAGE_EXTENSIONS.get(f".{extension}")


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
    """What a unit is over: code, or a seam an architecture record names."""

    FILE = "file"
    FUNCTION = "function"
    TYPE = "type"
    SEAM = "seam"


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
class Binding:
    """A name bound to a dotted name, as written: one name assigned another
    (`Payload = dict`, `o = order`), or an import (`from m import X as Y`
    binds Y to `m.X`; a relative import keeps its leading dots). Its line,
    and the definition it sits in (None at module level)."""

    path: str
    line: int
    within: str | None
    name: str
    value: str


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
class Complexity:
    """One function's complexity, as the complexity tooling measures it."""

    path: str
    symbol: str
    line: int
    value: int


@dataclass(frozen=True, slots=True)
class Span:
    """Lines start to end, inclusive, of one file."""

    path: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class Clone:
    """Two stretches of code alike, and how many lines they share."""

    first: Span
    second: Span
    lines: int


@dataclass(frozen=True, slots=True)
class Metrics:
    """Per-function complexity and the clones, merged into the CodeModel."""

    complexity: tuple[Complexity, ...] = ()
    clones: tuple[Clone, ...] = ()


@dataclass(frozen=True, slots=True)
class CodeModel:
    """Every fact an analyzer read from the sources, and their Metrics."""

    units: tuple[Unit, ...] = ()
    imports: tuple[ImportEdge, ...] = ()
    definitions: tuple[Definition, ...] = ()
    references: tuple[Reference, ...] = ()
    calls: tuple[Call, ...] = ()
    accesses: tuple[Access, ...] = ()
    writes: tuple[Write, ...] = ()
    bindings: tuple[Binding, ...] = ()
    conditionals: tuple[Conditional, ...] = ()
    members: tuple[Member, ...] = ()
    test_cases: tuple[TestCase, ...] = ()
    regions: tuple[Region, ...] = ()
    unparsed: tuple[Unparsed, ...] = ()
    metrics: Metrics = Metrics()

    def unit_at(self, path: str, line: int) -> Unit | None:
        """The innermost unit holding that line of that file: the smallest
        definition spanning it, else the file itself."""
        holding = [
            u
            for u in self.units
            if u.path == path and (u.kind is UnitKind.FILE or u.start <= line <= u.end)
        ]
        return min(
            holding,
            key=lambda u: (u.kind is UnitKind.FILE, u.end - u.start),
            default=None,
        )


# --- Pure helpers ------------------------------------------------------------


def merged(models: Sequence[CodeModel]) -> CodeModel:
    """One CodeModel holding every fact and metric of each, in order."""
    return CodeModel(
        units=tuple(f for m in models for f in m.units),
        imports=tuple(f for m in models for f in m.imports),
        definitions=tuple(f for m in models for f in m.definitions),
        references=tuple(f for m in models for f in m.references),
        calls=tuple(f for m in models for f in m.calls),
        accesses=tuple(f for m in models for f in m.accesses),
        writes=tuple(f for m in models for f in m.writes),
        bindings=tuple(f for m in models for f in m.bindings),
        conditionals=tuple(f for m in models for f in m.conditionals),
        members=tuple(f for m in models for f in m.members),
        test_cases=tuple(f for m in models for f in m.test_cases),
        regions=tuple(f for m in models for f in m.regions),
        unparsed=tuple(f for m in models for f in m.unparsed),
        metrics=Metrics(
            complexity=tuple(f for m in models for f in m.metrics.complexity),
            clones=tuple(f for m in models for f in m.metrics.clones),
        ),
    )
