"""adapters/astgrep.py -- structural facts from ast-grep, for every language.

The adapter owns one rule file per grammar under astgrep_rules/; each
rule's id names the fact it yields (`function`, `type`, ...) and its
captures are the fact's parts, so turning matches into CodeModel facts is
written once, whatever the language (ARCHITECTURE.ARCH-ADHERENCE.md,
Module map: adapters/astgrep.py).

ast-grep runs as a subprocess over a copy of the sources in a scratch
directory, never the repository: its configuration is the one written
there and named on the command line, ignore files are not read, links
are not followed, its environment is allowlisted, and the time left
before the deadline is its bound (Security mitigations).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, fields
from pathlib import Path, PurePosixPath

from adherence.domain.deadline import Deadline
from adherence.domain.declaration import Declaration, layer_of
from adherence.domain.model import (
    Access,
    AccessKind,
    Body,
    Call,
    CodeModel,
    Definition,
    ImportEdge,
    Parameter,
    Reference,
    ReferenceKind,
    Region,
    Signature,
    Unit,
    UnitKind,
    Write,
)
from adherence.domain.parameters import Vocabulary
from adherence.domain.source import source_lines

# --- Constants ---------------------------------------------------------------

RULES = Path(__file__).resolve().parent / "astgrep_rules"
BINARY = Path(sys.executable).with_name("ast-grep")
IGNORE_FILES = ("hidden", "dot", "exclude", "global", "parent", "vcs")
# Facts: each rule's id names one.
FUNCTION, FUNCTION_NODE, TYPE, IMPORT = "function", "function-node", "type", "import"
PARAMETER, PARAMETER_TYPE, PARAMETER_DEFAULT = (
    "parameter",
    "parameter-type",
    "parameter-default",
)
PARAMETER_PROPERTY, PROPERTY_DEFAULT, PROPERTY_TYPE = (
    "parameter-property",
    "property-default",
    "property-type",
)
BODY, STUB, CALL, NAME_FACT, STRING = "body", "stub", "call", "name", "string"
GLOBAL, WRITE = "global", "write"
RETURNS, BASE, DECORATOR, DECORATOR_NEXT = (
    "returns",
    "base",
    "decorator",
    "decorator-next",
)
# Captures: each names a part of its fact.
NAME, SOURCE, TYPE_CAPTURE = "NAME", "SOURCE", "TYPE"
BODY_CAPTURE, THROWN, CALLEE = "BODY", "THROWN", "CALLEE"
OBJECT, FIELD = "OBJECT", "FIELD"
EMPTY_BLOCK = "{}"

# --- Values ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Grammar:
    """One rule file, written for its first ast-grep language and run as
    each language named, with the file globs a language claims beyond its
    own extensions."""

    rules: str
    languages: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class Capture:
    """A part of a match: its text and its byte span in the file."""

    text: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class Match:
    """One node a rule matched: the fact it names (its rule's id before any
    `.variant`), the repository path, its byte span, its lines (from 1), its
    text and its captures."""

    fact: str
    path: str
    start: int
    end: int
    line: int
    end_line: int
    text: str
    captures: Mapping[str, Capture] = field(default_factory=dict)

    def holds(self, other: Match) -> bool:
        """Whether this node's span contains the other's."""
        return self.start <= other.start and other.end <= self.end

    def same_node(self, other: Match) -> bool:
        return (self.start, self.end) == (other.start, other.end)

    def captured(self, name: str) -> str | None:
        found = self.captures.get(name)
        return None if found is None else found.text


class ScanFailed(Exception):
    """ast-grep could not answer, or ran past the deadline."""

    def __init__(self, reason: str, *, timed_out: bool = False) -> None:
        super().__init__(reason)
        self.timed_out = timed_out


# --- Pure helpers ------------------------------------------------------------


def rule_text(grammar: Grammar, text: str) -> str:
    """The rule file run as every language of the grammar: each copy names
    its language and suffixes its ids with it, since ids must be unique."""
    copies: list[str] = []
    for language in grammar.languages:
        lines = []
        for line in text.splitlines():
            if line.startswith("language: "):
                line = f"language: {language}"
            elif line.startswith("id: "):
                line = f"{line}@{language}"
            lines.append(line)
        copies.append("\n".join(lines))
    return "\n---\n".join(copies) + "\n"


def config_text(grammar: Grammar) -> str:
    """The ast-grep project configuration written beside the copy."""
    globs = {
        language.lower(): list(claimed)
        for language, claimed in grammar.languages.items()
        if claimed
    }
    return json.dumps({"ruleDirs": ["rules"], "languageGlobs": globs})


def parse_match(record: Mapping[str, object], tree: str) -> Match:
    """One line of ast-grep's JSON stream as a Match keyed by repository path."""
    span = record["range"]
    assert isinstance(span, dict)
    single = record.get("metaVariables", {})
    assert isinstance(single, dict)
    captures = {
        name: Capture(
            str(value["text"]),
            int(value["range"]["byteOffset"]["start"]),
            int(value["range"]["byteOffset"]["end"]),
        )
        for name, value in single.get("single", {}).items()
    }
    return Match(
        fact=str(record["ruleId"]).split("@")[0].split(".")[0],
        path=str(PurePosixPath(str(record["file"])).relative_to(tree)),
        start=int(span["byteOffset"]["start"]),
        end=int(span["byteOffset"]["end"]),
        line=int(span["start"]["line"]) + 1,
        end_line=int(span["end"]["line"]) + 1,
        text=str(record["text"]),
        captures=captures,
    )


@dataclass(frozen=True, slots=True)
class _Defined:
    match: Match
    kind: UnitKind
    symbol: str
    parent: str | None


def innermost(
    nodes: Sequence[Match], inner: Match, *, strict: bool = False
) -> Match | None:
    """The smallest node whose span holds the inner one; with strict, never a
    node of the inner one's own span."""
    holding = [
        n for n in nodes if n.holds(inner) and not (strict and n.same_node(inner))
    ]
    return min(holding, key=lambda n: n.end - n.start, default=None)


def _defined(matches: Sequence[Match]) -> list[_Defined]:
    """Every definition of one file with its qualified symbol, in order."""
    nodes = sorted(
        (m for m in matches if m.fact in (FUNCTION, TYPE) and m.captured(NAME)),
        key=lambda m: (m.start, -m.end),
    )
    symbols: dict[tuple[int, int], str] = {}
    found: list[_Defined] = []
    for node in nodes:
        parent = innermost(nodes, node, strict=True)
        parent_symbol = symbols.get((parent.start, parent.end)) if parent else None
        name = node.captured(NAME) or ""
        symbol = f"{parent_symbol}.{name}" if parent_symbol else name
        symbols[(node.start, node.end)] = symbol
        kind = UnitKind.FUNCTION if node.fact == FUNCTION else UnitKind.TYPE
        found.append(_Defined(node, kind, symbol, parent_symbol))
    return found


def _of(matches: Sequence[Match], fact: str) -> list[Match]:
    return sorted((m for m in matches if m.fact == fact), key=lambda m: m.start)


def _at(matches: Sequence[Match], fact: str) -> dict[tuple[int, int], Match]:
    """A fact's matches by node span, to join it to the node it describes."""
    return {(m.start, m.end): m for m in matches if m.fact == fact}


def _annotation(text: str | None) -> str | None:
    """A type annotation's type as written, without the colon opening it."""
    return None if text is None else text.removeprefix(":").strip()


def _member_type(
    name: str, annotation: str | None, typed: Sequence[Match]
) -> str | None:
    """An options object member's type: from the object type written in
    place, or as the named type's member; None when there is no type."""
    if annotation is None:
        return None
    if annotation.startswith("{"):
        found = [m for m in typed if m.captured(NAME) == name]
        return _annotation(found[0].captured(TYPE_CAPTURE)) if found else None
    return f'{annotation}["{name}"]'


def _members_of(
    parameter: Match,
    matches: Sequence[Match],
    annotation: str | None,
    has_default: bool,
) -> list[Parameter]:
    """A destructured options object's members, each a keyword parameter."""
    parameters = _of(matches, PARAMETER)
    defaults = _at(matches, PROPERTY_DEFAULT)
    typed = [m for m in _of(matches, PROPERTY_TYPE) if parameter.holds(m)]
    return [
        Parameter(
            name,
            _member_type(name, annotation, typed),
            True,
            has_default or (member.start, member.end) in defaults,
        )
        for member in _of(matches, PARAMETER_PROPERTY)
        if parameter.holds(member)
        and (owner := innermost(parameters, member)) is not None
        and owner.same_node(parameter)
        and (name := member.captured(NAME)) is not None
    ]


def _signature(
    node: Match, matches: Sequence[Match], vocabulary: Vocabulary
) -> Signature:
    """A function's parameters, in order, and its return annotation."""
    functions = _of(matches, FUNCTION_NODE)
    typed = _at(matches, PARAMETER_TYPE)
    defaults = _at(matches, PARAMETER_DEFAULT)
    parameters: list[Parameter] = []
    for parameter in _of(matches, PARAMETER):
        owner = innermost(functions, parameter)
        if owner is None or not owner.same_node(node):
            continue
        span = (parameter.start, parameter.end)
        annotation = (
            _annotation(typed[span].captured(TYPE_CAPTURE)) if span in typed else None
        )
        has_default = span in defaults
        members = _members_of(parameter, matches, annotation, has_default)
        name = parameter.captured(NAME) or parameter.text
        parameters.extend(
            members
            or [
                Parameter(
                    name, annotation, name in vocabulary.options_objects, has_default
                )
            ]
        )
    returns = _at(matches, RETURNS).get((node.start, node.end))
    return Signature(
        tuple(parameters),
        _annotation(returns.captured(TYPE_CAPTURE)) if returns else None,
    )


def body_text(text: str) -> str:
    """A body as written: a block's lines inside its braces, from the first
    to the last holding anything, or an arrow's expression."""
    if not (text.startswith("{") and text.endswith("}")):
        return text
    inner = text[1:-1]
    lines = source_lines(inner)
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if len(lines) == 1:
        return lines[0].strip() if "\n" not in inner else lines[0].rstrip()
    return "\n".join(line.rstrip() for line in lines)


def _body(
    defined: _Defined,
    every: Sequence[_Defined],
    matches: Sequence[Match],
    vocabulary: Vocabulary,
) -> Body:
    """A definition's body: its text, the placeholder it is if it is nothing
    but one, and the lines it calls a sleep on outside nested definitions."""
    span = (defined.match.start, defined.match.end)
    body = _at(matches, BODY).get(span)
    stub = _at(matches, STUB).get(span)
    form = None if stub is None else stub.captured(THROWN) or EMPTY_BLOCK
    sleeps = sorted(
        {
            call.line
            for call in _of(matches, CALL)
            if vocabulary.is_sleep(_callee(call))
            and (owner := _owner(every, call)) is not None
            and owner.symbol == defined.symbol
        }
    )
    return Body(
        body_text(body.captured(BODY_CAPTURE) or "") if body else "",
        (form,) if form is not None and form in vocabulary.stubs else (),
        tuple(sleeps),
    )


def _callee(call: Match) -> str:
    """A call's callee as written, a chain broken over lines joined up."""
    return "".join(part.strip() for part in (call.captured(CALLEE) or "").splitlines())


def _owner(defined: Sequence[_Defined], match: Match) -> _Defined | None:
    """The innermost definition holding a match."""
    found = innermost([d.match for d in defined], match)
    return next((d for d in defined if found and d.match.same_node(found)), None)


def _decorated(
    defined: Sequence[_Defined], matches: Sequence[Match]
) -> dict[str, list[str]]:
    """Each definition's decorators by symbol: one inside a class is the
    class's; one before an export or a method is the next definition's."""
    found: dict[str, list[str]] = {}
    for decorator in _of(matches, DECORATOR):
        owner = _owner(defined, decorator)
        if owner is not None:
            found.setdefault(owner.symbol, []).append(decorator.captured(NAME) or "")
    for decorator in _of(matches, DECORATOR_NEXT):
        following = [d for d in defined if d.match.start >= decorator.end]
        if following:
            found.setdefault(following[0].symbol, []).append(
                decorator.captured(NAME) or ""
            )
    return found


def definitions(
    path: str,
    matches: Sequence[Match],
    declaration: Declaration,
    regions: Sequence[Region],
    vocabulary: Vocabulary,
) -> list[Definition]:
    """The definitions of one file, each in the layer of its first line."""
    defined = _defined(matches)
    functions = _of(matches, FUNCTION_NODE)
    bases: dict[str, list[str]] = {}
    for base in _of(matches, BASE):
        owner = _owner(defined, base)
        if owner is not None and owner.kind is UnitKind.TYPE:
            bases.setdefault(owner.symbol, []).append(base.captured(NAME) or "")
    decorators = _decorated(defined, matches)
    return [
        Definition(
            unit=Unit(
                path,
                d.kind,
                d.symbol,
                d.match.line,
                d.match.end_line,
                layer_of(path, d.match.line, declaration, regions),
            ),
            signature=_signature(d.match, matches, vocabulary)
            if d.kind is UnitKind.FUNCTION
            else None,
            body=_body(d, defined, matches, vocabulary),
            bases=tuple(bases.get(d.symbol, ())),
            decorators=tuple(decorators.get(d.symbol, ())),
            parent=d.parent,
            nested=any(
                f.holds(d.match) and not f.same_node(d.match) for f in functions
            ),
        )
        for d in defined
    ]


def imports(
    path: str, matches: Sequence[Match], lines: Sequence[str]
) -> list[ImportEdge]:
    """The imports of one file: the module as written, the line and its
    text; which file each resolves to is the language adapter's to say."""
    return [
        ImportEdge(path, source, m.line, lines[m.line - 1].strip(), None)
        for m in sorted(matches, key=lambda m: m.start)
        if m.fact == IMPORT and (source := m.captured(SOURCE)) is not None
    ]


def _within(defined: Sequence[_Defined], match: Match) -> str | None:
    owner = _owner(defined, match)
    return None if owner is None else owner.symbol


def references(
    path: str, matches: Sequence[Match], defined: Sequence[_Defined]
) -> list[Reference]:
    """Every name, dotted chain and type name, and every string literal but
    an import's module, with the definition each sits in."""
    found = [
        Reference(path, m.line, _within(defined, m), ReferenceKind.NAME, m.text)
        for m in _of(matches, NAME_FACT)
    ]
    found.extend(
        Reference(path, m.line, _within(defined, m), ReferenceKind.STRING, m.text[1:-1])
        for m in _of(matches, STRING)
    )
    return sorted(found, key=lambda r: r.line)


def calls(
    path: str, matches: Sequence[Match], defined: Sequence[_Defined]
) -> list[Call]:
    """Every function and constructor call, with the definition it sits in."""
    return [
        Call(path, m.line, _within(defined, m), _callee(m)) for m in _of(matches, CALL)
    ]


def accesses(
    path: str,
    matches: Sequence[Match],
    defined: Sequence[_Defined],
    vocabulary: Vocabulary,
) -> list[Access]:
    """Every name chain Vocabulary counts as reading the environment, and
    every read of the language's global object, with its definition."""
    found = [
        Access(path, m.line, _within(defined, m), AccessKind.ENVIRONMENT, m.text)
        for m in _of(matches, NAME_FACT)
        if vocabulary.reads_environment(m.text)
    ]
    found.extend(
        Access(path, m.line, _within(defined, m), AccessKind.GLOBAL, m.text)
        for m in _of(matches, GLOBAL)
    )
    return sorted(found, key=lambda a: a.line)


def writes(
    path: str, matches: Sequence[Match], defined: Sequence[_Defined]
) -> list[Write]:
    """Every assignment, update or compound assignment to an object's field,
    with the definition that makes it."""
    return [
        Write(
            path,
            m.line,
            _within(defined, m),
            m.captured(OBJECT) or "",
            m.captured(FIELD) or "",
        )
        for m in _of(matches, WRITE)
    ]


def file_model(
    path: str,
    data: bytes,
    matches: Sequence[Match],
    declaration: Declaration,
    regions: Sequence[Region],
    vocabulary: Vocabulary,
) -> CodeModel:
    """Every fact of one file, as a CodeModel of that file alone; its imports
    say which file each resolves to only once the language adapter has."""
    lines = source_lines(data.decode("utf-8", "replace"))
    file_unit = Unit(
        path, UnitKind.FILE, None, 1, len(lines), layer_of(path, None, declaration)
    )
    defined = _defined(matches)
    found = definitions(path, matches, declaration, regions, vocabulary)
    return CodeModel(
        units=(file_unit, *(d.unit for d in found)),
        definitions=tuple(found),
        imports=tuple(imports(path, matches, lines)),
        references=tuple(references(path, matches, defined)),
        calls=tuple(calls(path, matches, defined)),
        accesses=tuple(accesses(path, matches, defined, vocabulary)),
        writes=tuple(writes(path, matches, defined)),
    )


def merged(models: Sequence[CodeModel], **rest: object) -> CodeModel:
    """One CodeModel holding every fact of each, with the fields given in
    place of theirs."""
    joined: dict[str, object] = {
        f.name: tuple(fact for m in models for fact in getattr(m, f.name))
        for f in fields(CodeModel)
    }
    joined.update(rest)
    return CodeModel(**joined)  # type: ignore[arg-type]  # every field is a tuple


# --- Effectful helpers -------------------------------------------------------


def write_tree(tree: Path, sources: Mapping[str, bytes]) -> None:
    for path, data in sources.items():
        target = tree / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def scan(
    sources: Mapping[str, bytes],
    grammar: Grammar,
    *,
    binary: Path,
    deadline: Deadline | None,
    clock: Callable[[], float],
) -> list[Match]:
    """Every match of the grammar's rules over the sources, keyed by
    repository path. Raises ScanFailed when ast-grep cannot answer in time."""
    if not binary.is_file():
        raise ScanFailed(f"ast-grep is not installed at {binary}")
    timeout = None
    if deadline is not None:
        timeout = deadline.epoch_seconds - clock()
        if timeout <= 0:
            raise ScanFailed("scan the sources", timed_out=True)
    with tempfile.TemporaryDirectory(prefix="adhere-astgrep-") as scratch:
        root = Path(scratch)
        (root / "rules").mkdir()
        rules = (RULES / grammar.rules).read_text()
        (root / "rules" / "rules.yml").write_text(rule_text(grammar, rules))
        (root / "sgconfig.yml").write_text(config_text(grammar))
        write_tree(root / "tree", sources)
        command = [
            str(binary),
            "scan",
            "--config",
            str(root / "sgconfig.yml"),
            "--json=stream",
            "--color",
            "never",
            *(f"--no-ignore={kind}" for kind in IGNORE_FILES),
            "tree",
        ]
        environment = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LANG": "C.UTF-8",
            "HOME": scratch,
            "TMPDIR": scratch,
        }
        try:
            done = subprocess.run(
                command,
                capture_output=True,
                check=True,
                cwd=scratch,
                env=environment,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as expired:
            raise ScanFailed("scan the sources", timed_out=True) from expired
        except subprocess.CalledProcessError as failed:
            complaint = failed.stderr.decode("utf-8", "replace").strip().splitlines()
            reason = complaint[0] if complaint else f"exit {failed.returncode}"
            raise ScanFailed(f"ast-grep failed: {reason}") from failed
    return [
        parse_match(json.loads(line), "tree")
        for line in done.stdout.decode("utf-8", "replace").splitlines()
        if line.strip()
    ]
