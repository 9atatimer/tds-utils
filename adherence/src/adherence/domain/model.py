"""domain/model.py -- the CodeModel: the language-neutral facts every check reads.

Every analyzer produces one CodeModel; every check reads only that
(ARCHITECTURE.ARCH-ADHERENCE.md, Module map and Key Decisions).
"""

from __future__ import annotations

import enum
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, fields, replace

# --- Values ------------------------------------------------------------------


class CodeLanguage(enum.Enum):
    """A language the suite measures; named so it never collides with the
    Language check (ARCHITECTURE.ARCH-ADHERENCE.md, Use-case surface)."""

    PYTHON = "python"
    TYPESCRIPT = "typescript"
    JAVASCRIPT = "javascript"
    SHELL = "shell"


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
    ".sh": CodeLanguage.SHELL.value,
    ".bash": CodeLanguage.SHELL.value,
    ".zsh": CodeLanguage.SHELL.value,
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


# The interpreters whose scripts the shell analyzer reads, when the file
# has no extension to say so (ARCHITECTURE.ARCH-ADHERENCE.md, Key
# Decisions, a shell script by its shebang; Issue#638).
SHEBANG_SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh"})
# An interpreter name repeated in a coverage reason: it is author text, so
# it is bounded and plain; any other name is reported as "unknown".
INTERPRETER_NAME = re.compile(r"[A-Za-z0-9._+-]{1,32}")
# env's options that take the next word as their argument.
ENV_OPTIONS_WITH_ARGUMENT = frozenset({"-u", "--unset", "-C", "--chdir"})


def has_no_extension(path: str) -> bool:
    """Whether a path's name has no extension; a leading dot is not one."""
    name = path.rpartition("/")[2]
    return "." not in name.lstrip(".")


def _interpreter(text: bytes) -> str | None:
    """The program a script's `#!` line names, through `env` when it is
    run by env; None when the first line is no usable shebang."""
    first = text.split(b"\n", 1)[0]
    if not first.startswith(b"#!"):
        return None
    words = first[2:].decode("utf-8", "replace").split()
    if words and words[0].rpartition("/")[2] == "env":
        words = _env_command(words[1:])
    return words[0].rpartition("/")[2] if words else None


def _env_command(words: list[str]) -> list[str]:
    """The command env runs: its words after env's own options, an option's
    argument (`-u NAME`, `-C DIR`) and NAME=value settings."""
    rest = list(words)
    while rest:
        word = rest.pop(0)
        if word in ENV_OPTIONS_WITH_ARGUMENT:
            if rest:
                rest.pop(0)
        elif not (word.startswith("-") or "=" in word):
            return [word, *rest]
    return []


def script_language(text: bytes) -> str | None:
    """The language a file with no extension is written in, by its shebang:
    shell for a shell, else the interpreter's name; None with no shebang."""
    interpreter = _interpreter(text)
    if interpreter is None:
        return None
    if interpreter in SHEBANG_SHELLS:
        return CodeLanguage.SHELL.value
    return interpreter if INTERPRETER_NAME.fullmatch(interpreter) else "unknown"


def code_language_of(path: str) -> CodeLanguage | None:
    """The measured language a source path is written in; None when the
    suite does not measure it."""
    name = language_of(path)
    return next((c for c in CodeLanguage if c.value == name), None)


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
    """What a unit is over: code, a seam an architecture record names, or a
    design behavior a design record states."""

    FILE = "file"
    FUNCTION = "function"
    TYPE = "type"
    SEAM = "seam"
    BEHAVIOR = "design behavior"


@dataclass(frozen=True, slots=True)
class Unit:
    """What a check is over: a file, or a function or type in it, with its
    qualified symbol (None for a file), its lines and its layer (None when
    the declaration does not cover it). `language` is set on a file whose
    name does not say its language, as a script with no extension does;
    otherwise the path's extension says it."""

    path: str
    kind: UnitKind
    symbol: str | None
    start: int
    end: int
    layer: Layer | None
    language: str | None = None


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
    is nothing but one (`pass`, `...`) or the stub exception it raises
    (`NotImplementedError`, whatever precedes it), and the lines where it
    sleeps. Nested definitions are their own bodies."""

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
class Target:
    """What a call's callee stands for, read through its file's imports and
    definitions: the dotted name, and the repository definition it names --
    its path, and its symbol there -- when it is one of the repository's."""

    name: str
    path: str | None = None
    symbol: str | None = None


@dataclass(frozen=True, slots=True)
class Call:
    """A function or constructor call: its callee as written, its line, the
    definition it sits in, and what the callee resolves to (None when the
    analyzer cannot tell, as for a method of a local variable). Reading an
    attribute by a literal name (`getattr(rules, "_round")`) is a call to
    it."""

    path: str
    line: int
    within: str | None
    callee: str
    target: Target | None = None


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
class Assertion:
    """One asserted expression, as written, its truth value when it is a
    literal (None when it is not), and whether the assertion carries a
    message."""

    text: str
    truth: bool | None = None
    message: bool = False


@dataclass(frozen=True, slots=True)
class TestCase:
    """A test: its symbol, its line, the callees it calls, and the
    expressions it asserts."""

    __test__ = False  # a domain value, not a pytest class

    path: str
    symbol: str
    line: int
    calls: tuple[str, ...]
    assertions: tuple[Assertion, ...]


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
class MetricsUnavailable:
    """The complexity or duplication tooling could not measure -- absent,
    or failed -- with the reason, naming the tool."""

    reason: str


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


def _path_of(fact: object) -> str:
    """The file a fact was read from: a definition's unit's, else its own."""
    if isinstance(fact, Definition):
        return fact.unit.path
    # The fact families share no base type; each carries a path field.
    path = getattr(fact, "path")  # noqa: B009
    assert isinstance(path, str)
    return path


def _touches(fact: object, out: frozenset[str]) -> bool:
    """Whether a metric is about a dropped file: a clone when either of its
    two stretches is, any other metric by its path."""
    if isinstance(fact, Clone):
        return fact.first.path in out or fact.second.path in out
    return _path_of(fact) in out


def without(model: CodeModel, paths: Collection[str]) -> CodeModel:
    """The CodeModel with no fact of the files given: their units, the facts
    read from them, their regions and metrics, and each clone touching one.
    Every fact family is walked from the CodeModel's own fields, so a family
    added later is filtered without an edit here (Issue#642)."""
    out = frozenset(paths)
    families = {
        f.name: tuple(
            fact for fact in getattr(model, f.name) if _path_of(fact) not in out
        )
        for f in fields(CodeModel)
        if f.name != "metrics"
    }
    metrics = {
        f.name: tuple(
            fact for fact in getattr(model.metrics, f.name) if not _touches(fact, out)
        )
        for f in fields(Metrics)
    }
    return CodeModel(**families, metrics=Metrics(**metrics))


def with_languages(model: CodeModel, languages: Mapping[str, str]) -> CodeModel:
    """The CodeModel with each file unit of the paths given marked in its
    language, for files whose name does not say it."""
    return replace(
        model,
        units=tuple(
            replace(u, language=languages[u.path])
            if u.kind is UnitKind.FILE and u.path in languages
            else u
            for u in model.units
        ),
    )
