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

import bisect
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, fields
from pathlib import Path, PurePosixPath

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
    ImportEdge,
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
GLOBAL, WRITE, SYNTAX_ERROR = "global", "write", "syntax-error"
MEMBER_METHOD, MEMBER_FIELD, TEST_CALL = "member-method", "member-field", "test-call"
CONDITIONAL, EITHER, COMPARE, NEGATE, GROUP, TYPEOF = (
    "conditional",
    "either",
    "compare",
    "negate",
    "group",
    "typeof",
)
RETURNS, BASE, DECORATOR, DECORATOR_NEXT = (
    "returns",
    "base",
    "decorator",
    "decorator-next",
)
# Captures: each names a part of its fact.
NAME, SOURCE, TYPE_CAPTURE = "NAME", "SOURCE", "TYPE"
BODY_CAPTURE, THROWN, CALLEE = "BODY", "THROWN", "CALLEE"
OBJECT, FIELD, TITLE, CASE = "OBJECT", "FIELD", "TITLE", "CASE"
MISSING = "MISSING"
QUOTES = ("'", '"', "`")
CONDITION, SUBJECT, LEFT, RIGHT, OPERAND, INNER = (
    "CONDITION",
    "SUBJECT",
    "LEFT",
    "RIGHT",
    "OPERAND",
    "INNER",
)
EMPTY_BLOCK = "{}"
NESTED_TOO_DEEPLY = "nested deeper than the analyzer can walk"
LEAVES = "the path leaves the repository; not read"
# The path a line of ast-grep's stream names, read without decoding the
# line, for a line that does not decode.
FILE_FIELD = re.compile(r'"file"\s*:\s*("(?:[^"\\]|\\.)*")')
REST = "..."
THIS = "this"

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
    """A part of a match: its text, its byte span in the file and its line
    (from 1)."""

    text: str
    start: int
    end: int
    line: int


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


Span = tuple[int, int]


@dataclass(frozen=True, slots=True)
class Scanned:
    """The structural pass over one language's sources: each parsed file's
    CodeModel, the sources parsed, why each other source is not, and the
    regions (declared by lines, then found by marker) of the files handed
    over. A language adapter adds what ast-grep cannot say, such as where
    an import resolves."""

    files: tuple[CodeModel, ...]
    parsed: Mapping[str, bytes]
    unparsed: tuple[Unparsed, ...]
    regions: tuple[Region, ...]


@dataclass(frozen=True, slots=True)
class _Defined:
    """A named definition: its node, its kind, its qualified symbol and the
    symbol of the definition holding it."""

    match: Match
    kind: UnitKind
    symbol: str
    parent: str | None


@dataclass(frozen=True, slots=True)
class _File:
    """One file's matches by fact, its definitions, and the innermost
    definition holding each match."""

    path: str
    facts: Mapping[str, Sequence[Match]]
    defined: Sequence[_Defined]
    owner: Mapping[tuple[int, int, str], _Defined]

    def of(self, fact: str) -> Sequence[Match]:
        """A fact's matches, in the order they start."""
        return self.facts.get(fact, ())

    def owner_of(self, match: Match) -> _Defined | None:
        return self.owner.get((match.start, match.end, match.fact))

    def within(self, match: Match) -> str | None:
        """The symbol of the definition a match sits in; None at the top."""
        owner = self.owner_of(match)
        return None if owner is None else owner.symbol


@dataclass(frozen=True, slots=True)
class _Expressions:
    """One file's expressions a discriminant is read through, by span."""

    either: Mapping[Span, Match]
    compare: Mapping[Span, Match]
    negate: Mapping[Span, Match]
    group: Mapping[Span, Match]
    call: Mapping[Span, Match]
    typeof: Mapping[Span, Match]


# --- Pure helpers ------------------------------------------------------------


def stays_inside(path: str) -> bool:
    """Whether a repository path names a file inside the repository: relative
    and never climbing out, so a copy written by it stays in its directory."""
    pure = PurePosixPath(path)
    return bool(pure.parts) and not pure.is_absolute() and ".." not in pure.parts


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
            text=str(value["text"]),
            start=int(value["range"]["byteOffset"]["start"]),
            end=int(value["range"]["byteOffset"]["end"]),
            line=int(value["range"]["start"]["line"]) + 1,
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


def named_path(line: str, tree: str) -> str | None:
    """The repository path a line of ast-grep's stream names, or None when
    none can be read from it."""
    found = FILE_FIELD.search(line)
    if found is None:
        return None
    try:
        return str(PurePosixPath(json.loads(found.group(1))).relative_to(tree))
    except ValueError:
        return None


def parse_stream(text: str, tree: str) -> tuple[list[Match], dict[str, str]]:
    """ast-grep's JSON stream as Matches, one record per line ended by
    "\n" alone (a source's own separators, U+2028 and kin, sit inside its
    strings), and why each file a line that does not decode names is not
    read. Raises ScanFailed when such a line names no file."""
    matches: list[Match] = []
    undecoded: dict[str, str] = {}
    for line in text.split("\n"):
        if not line.strip():
            continue
        try:
            matches.append(parse_match(json.loads(line), tree))
        except ValueError as error:
            path = named_path(line, tree)
            if path is None:
                raise ScanFailed(f"ast-grep's output is not JSON: {error}") from error
            undecoded.setdefault(path, f"ast-grep's output for it is not JSON: {error}")
    return matches, undecoded


def innermost_each(
    nodes: Sequence[Match], items: Sequence[Match], *, strict: bool = False
) -> list[Match | None]:
    """For each item, the smallest node whose span holds it (with strict,
    never one of the item's own span), in one sweep: the spans are a
    syntax tree's, so any two are nested or apart."""
    ordered = sorted(nodes, key=lambda n: (n.start, -n.end))
    found: list[Match | None] = [None] * len(items)
    stack: list[Match] = []
    taken = 0
    for index in sorted(
        range(len(items)), key=lambda i: (items[i].start, -items[i].end)
    ):
        item = items[index]
        while taken < len(ordered) and (ordered[taken].start, -ordered[taken].end) <= (
            item.start,
            -item.end,
        ):
            while stack and not stack[-1].holds(ordered[taken]):
                stack.pop()
            stack.append(ordered[taken])
            taken += 1
        while stack and not stack[-1].holds(item):
            stack.pop()
        holding = [n for n in stack[-2:] if not (strict and n.same_node(item))]
        found[index] = holding[-1] if holding else None
    return found


def _by_fact(matches: Sequence[Match]) -> dict[str, list[Match]]:
    found: dict[str, list[Match]] = {}
    for m in sorted(matches, key=lambda m: m.start):
        found.setdefault(m.fact, []).append(m)
    return found


def _spans(matches: Sequence[Match]) -> dict[Span, Match]:
    """Matches by node span, to join a fact to the node it describes."""
    return {(m.start, m.end): m for m in matches}


def _defined(functions: Sequence[Match], types: Sequence[Match]) -> list[_Defined]:
    """Every named definition of one file with its qualified symbol, in order."""
    nodes = sorted(
        (m for m in (*functions, *types) if m.captured(NAME)),
        key=lambda m: (m.start, -m.end),
    )
    symbols: dict[Span, str] = {}
    found: list[_Defined] = []
    for node, parent in zip(
        nodes, innermost_each(nodes, nodes, strict=True), strict=True
    ):
        parent_symbol = symbols.get((parent.start, parent.end)) if parent else None
        name = node.captured(NAME) or ""
        symbol = f"{parent_symbol}.{name}" if parent_symbol else name
        symbols[(node.start, node.end)] = symbol
        kind = UnitKind.FUNCTION if node.fact == FUNCTION else UnitKind.TYPE
        found.append(_Defined(node, kind, symbol, parent_symbol))
    return found


def _index(path: str, matches: Sequence[Match]) -> _File:
    """One file's matches, indexed once for every fact built from them."""
    facts = _by_fact(matches)
    defined = _defined(facts.get(FUNCTION, []), facts.get(TYPE, []))
    by_span = {(d.match.start, d.match.end): d for d in defined}
    every = [m for group in facts.values() for m in group]
    owners = innermost_each([d.match for d in defined], every)
    return _File(
        path=path,
        facts=facts,
        defined=defined,
        owner={
            (m.start, m.end, m.fact): by_span[(o.start, o.end)]
            for m, o in zip(every, owners, strict=True)
            if o is not None
        },
    )


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


def starred(name: str) -> str:
    """A parameter's name, a rest parameter's in the starred form every
    language's Parameter uses (`*rest`)."""
    return f"*{name[len(REST) :]}" if name.startswith(REST) else name


def _signatures(file: _File, vocabulary: Vocabulary) -> dict[Span, Signature]:
    """Each function node's parameters, in order, and its return annotation:
    a parameter is the innermost function node's holding it, a destructured
    object's members are keyword parameters, and so is a parameter that
    Vocabulary names as an options object."""
    parameters = file.of(PARAMETER)
    typed = _spans(file.of(PARAMETER_TYPE))
    defaults = _spans(file.of(PARAMETER_DEFAULT))
    member_defaults = _spans(file.of(PROPERTY_DEFAULT))
    properties = file.of(PARAMETER_PROPERTY)
    member_types = file.of(PROPERTY_TYPE)
    owners = innermost_each(file.of(FUNCTION_NODE), parameters)
    members: dict[Span, list[Match]] = {}
    for member, holder in zip(
        properties, innermost_each(parameters, properties), strict=True
    ):
        if holder is not None:
            members.setdefault((holder.start, holder.end), []).append(member)
    found: dict[Span, list[Parameter]] = {}
    for parameter, owner in zip(parameters, owners, strict=True):
        if owner is None:
            continue
        span = (parameter.start, parameter.end)
        annotation = (
            _annotation(typed[span].captured(TYPE_CAPTURE)) if span in typed else None
        )
        has_default = span in defaults
        name = starred(parameter.captured(NAME) or parameter.text)
        written = [m for m in member_types if parameter.holds(m)] if annotation else []
        given = [
            Parameter(
                name=member_name,
                annotation=_member_type(member_name, annotation, written),
                keyword_only=True,
                has_default=has_default
                or (member.start, member.end) in member_defaults,
            )
            for member in members.get(span, [])
            if (member_name := member.captured(NAME)) is not None
        ] or [
            Parameter(
                name=name,
                annotation=annotation,
                keyword_only=name in vocabulary.options_objects,
                has_default=has_default,
            )
        ]
        found.setdefault((owner.start, owner.end), []).extend(given)
    returns = _spans(file.of(RETURNS))
    return {
        span: Signature(
            tuple(found.get(span, [])),
            _annotation(returns[span].captured(TYPE_CAPTURE))
            if span in returns
            else None,
        )
        for span in {(f.start, f.end) for f in file.of(FUNCTION_NODE)}
    }


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


def _bodies(file: _File, vocabulary: Vocabulary) -> dict[str, Body]:
    """Each definition's body by symbol: its text, the placeholder it is if
    it is nothing but one, and the lines it calls a sleep on outside nested
    definitions."""
    bodies = _spans(file.of(BODY))
    stubs = _spans(file.of(STUB))
    sleeps: dict[str, set[int]] = {}
    for call in file.of(CALL):
        owner = file.owner_of(call)
        if owner is not None and vocabulary.is_sleep(_callee(call)):
            sleeps.setdefault(owner.symbol, set()).add(call.line)
    found: dict[str, Body] = {}
    for d in file.defined:
        span = (d.match.start, d.match.end)
        stub = stubs.get(span)
        form = None if stub is None else stub.captured(THROWN) or EMPTY_BLOCK
        body = bodies.get(span)
        found[d.symbol] = Body(
            body_text(body.captured(BODY_CAPTURE) or "") if body else "",
            (form,) if form is not None and form in vocabulary.stubs else (),
            tuple(sorted(sleeps.get(d.symbol, ()))),
        )
    return found


def joined(text: str) -> str:
    """Code as written with its lines joined up, a chain broken over lines
    read as one."""
    return "".join(part.strip() for part in text.splitlines())


def _callee(call: Match) -> str:
    return joined(call.captured(CALLEE) or "")


def _title(text: str) -> str:
    """A test's title: a string literal's text, or the expression as written."""
    if len(text) >= 2 and text[0] == text[-1] and text[0] in QUOTES:
        return text[1:-1]
    return joined(text)


def _decorated(file: _File) -> dict[str, list[str]]:
    """Each definition's decorators by symbol: one inside a class is the
    class's; one before an export or a method is the next definition's."""
    found: dict[str, list[str]] = {}
    for decorator in file.of(DECORATOR):
        owner = file.owner_of(decorator)
        if owner is not None:
            found.setdefault(owner.symbol, []).append(decorator.captured(NAME) or "")
    starts = [d.match.start for d in file.defined]
    for decorator in file.of(DECORATOR_NEXT):
        following = bisect.bisect_left(starts, decorator.end)
        if following < len(file.defined):
            found.setdefault(file.defined[following].symbol, []).append(
                decorator.captured(NAME) or ""
            )
    return found


def definitions(
    file: _File,
    declaration: Declaration,
    regions: Sequence[Region],
    vocabulary: Vocabulary,
) -> list[Definition]:
    """The definitions of one file, each in the layer of its first line."""
    bases: dict[str, list[str]] = {}
    for base in file.of(BASE):
        owner = file.owner_of(base)
        if owner is not None and owner.kind is UnitKind.TYPE:
            bases.setdefault(owner.symbol, []).append(base.captured(NAME) or "")
    decorators = _decorated(file)
    signatures = _signatures(file, vocabulary)
    bodies = _bodies(file, vocabulary)
    enclosing = innermost_each(
        file.of(FUNCTION_NODE), [d.match for d in file.defined], strict=True
    )
    return [
        Definition(
            unit=Unit(
                path=file.path,
                kind=d.kind,
                symbol=d.symbol,
                start=d.match.line,
                end=d.match.end_line,
                layer=layer_of(file.path, d.match.line, declaration, regions),
            ),
            signature=signatures.get((d.match.start, d.match.end))
            if d.kind is UnitKind.FUNCTION
            else None,
            body=bodies[d.symbol],
            bases=tuple(bases.get(d.symbol, ())),
            decorators=tuple(decorators.get(d.symbol, ())),
            parent=d.parent,
            nested=function is not None,
        )
        for d, function in zip(file.defined, enclosing, strict=True)
    ]


def imports(file: _File, lines: Sequence[str]) -> list[ImportEdge]:
    """The imports of one file: the module as written, the line and its
    text; which file each resolves to is the language adapter's to say."""
    return [
        ImportEdge(
            path=file.path,
            imported=source,
            line=m.line,
            text=lines[m.line - 1].strip(),
            imported_path=None,
        )
        for m in file.of(IMPORT)
        if (source := m.captured(SOURCE)) is not None
    ]


def references(file: _File) -> list[Reference]:
    """Every name, dotted chain and type name, and every string literal but
    an import's module, with the definition each sits in."""
    found = [
        Reference(file.path, m.line, file.within(m), ReferenceKind.NAME, m.text)
        for m in file.of(NAME_FACT)
    ]
    found.extend(
        Reference(file.path, m.line, file.within(m), ReferenceKind.STRING, m.text[1:-1])
        for m in file.of(STRING)
    )
    return sorted(found, key=lambda r: r.line)


def calls(file: _File) -> list[Call]:
    """Every function and constructor call, with the definition it sits in."""
    return [
        Call(path=file.path, line=m.line, within=file.within(m), callee=_callee(m))
        for m in file.of(CALL)
    ]


def accesses(file: _File, vocabulary: Vocabulary) -> list[Access]:
    """Every name chain Vocabulary counts as reading the environment, and
    every read of the language's global object, with its definition."""
    found = [
        Access(file.path, m.line, file.within(m), AccessKind.ENVIRONMENT, m.text)
        for m in file.of(NAME_FACT)
        if vocabulary.reads_environment(m.text)
    ]
    found.extend(
        Access(file.path, m.line, file.within(m), AccessKind.GLOBAL, m.text)
        for m in file.of(GLOBAL)
    )
    return sorted(found, key=lambda a: a.line)


def writes(file: _File) -> list[Write]:
    """Every field an assignment, update, compound assignment, destructuring
    or for-in/of header binds, with the definition that makes it."""
    return [
        Write(
            path=file.path,
            line=m.line,
            within=file.within(m),
            target=m.captured(OBJECT) or "",
            field=m.captured(FIELD) or "",
        )
        for m in file.of(WRITE)
    ]


def _span(capture: Capture) -> Span:
    return (capture.start, capture.end)


def discriminants(capture: Capture, found: _Expressions) -> list[str]:
    """What a branch's test discriminates on: through parentheses, each
    operand of a logical operator, the operand of a negation, the left of a
    comparison (the operand of a typeof compared, on either side), the
    callee of a call, or else the expression as written."""
    span = _span(capture)
    if span in found.group:
        return discriminants(found.group[span].captures[INNER], found)
    if span in found.either:
        both = found.either[span].captures
        return discriminants(both[LEFT], found) + discriminants(both[RIGHT], found)
    if span in found.negate:
        return discriminants(found.negate[span].captures[OPERAND], found)
    if span in found.compare:
        sides = found.compare[span].captures
        tested = [
            found.typeof[_span(side)].captures[OPERAND].text
            for side in (sides[LEFT], sides[RIGHT])
            if _span(side) in found.typeof
        ]
        return tested[:1] or [sides[LEFT].text]
    if span in found.call:
        return [_callee(found.call[span])]
    return [capture.text]


def conditionals(file: _File) -> list[Conditional]:
    """Every branch, one per expression it discriminates on; a switch on its
    subject as written."""
    found = _Expressions(
        either=_spans(file.of(EITHER)),
        compare=_spans(file.of(COMPARE)),
        negate=_spans(file.of(NEGATE)),
        group=_spans(file.of(GROUP)),
        call=_spans(file.of(CALL)),
        typeof=_spans(file.of(TYPEOF)),
    )
    branches: list[Conditional] = []
    for m in file.of(CONDITIONAL):
        within = file.within(m)
        if CONDITION in m.captures:
            tests = discriminants(m.captures[CONDITION], found)
        else:
            tests = [m.captured(SUBJECT) or ""]
        branches.extend(
            Conditional(path=file.path, line=m.line, within=within, discriminant=test)
            for test in tests
        )
    return branches


def members(file: _File) -> list[Member]:
    """Every type's fields and methods, each name once at its first line:
    declared, a constructor's parameter property, or a field of `this`
    written (the same targets as every Write)."""
    types = [d for d in file.defined if d.kind is UnitKind.TYPE]
    by_span = {(d.match.start, d.match.end): d for d in types}
    kinds = {
        MEMBER_METHOD: MemberKind.METHOD,
        MEMBER_FIELD: MemberKind.FIELD,
        WRITE: MemberKind.FIELD,
    }
    found = sorted(
        (
            m
            for fact in kinds
            for m in file.of(fact)
            if fact != WRITE or m.captured(OBJECT) == THIS
        ),
        key=lambda m: (m.line, m.start),
    )
    first: dict[tuple[str, str], Member] = {}
    for m, holder in zip(
        found, innermost_each([d.match for d in types], found), strict=True
    ):
        name = m.captured(FIELD if m.fact == WRITE else NAME)
        if holder is not None and name is not None:
            owner = by_span[(holder.start, holder.end)]
            member = Member(
                path=file.path,
                owner=owner.symbol,
                name=name,
                kind=kinds[m.fact],
                line=m.line,
            )
            first.setdefault((owner.symbol, name), member)
    return list(first.values())


def test_cases(file: _File, vocabulary: Vocabulary) -> list[TestCase]:
    """Every call Vocabulary counts as declaring a test, with the callees its
    case calls outside nested definitions and the outermost calls in it that
    Vocabulary counts as asserting."""
    every = file.of(CALL)
    starts = [c.start for c in every]
    cases: list[TestCase] = []
    for m in file.of(TEST_CALL):
        if not vocabulary.declares_test(_callee(m)):
            continue
        case, within = m.captures[CASE], file.within(m)
        inside = [
            c
            for c in every[bisect.bisect_left(starts, case.start) :]
            if c.start < case.end and c.end <= case.end and file.within(c) == within
        ]
        asserting = [c for c in inside if vocabulary.asserts(_callee(c))]
        outermost = [
            a for a in asserting if not any(o.holds(a) and o != a for o in asserting)
        ]
        cases.append(
            TestCase(
                path=file.path,
                symbol=_title(m.captured(TITLE) or ""),
                line=m.line,
                calls=tuple(_callee(c) for c in inside if c not in asserting),
                assertions=tuple(joined(a.text) for a in outermost),
            )
        )
    return cases


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
        path=path,
        kind=UnitKind.FILE,
        symbol=None,
        start=1,
        end=len(lines),
        layer=layer_of(path, None, declaration),
    )
    file = _index(path, matches)
    found = definitions(file, declaration, regions, vocabulary)
    return CodeModel(
        units=(file_unit, *(d.unit for d in found)),
        definitions=tuple(found),
        imports=tuple(imports(file, lines)),
        references=tuple(references(file)),
        calls=tuple(calls(file)),
        accesses=tuple(accesses(file, vocabulary)),
        writes=tuple(writes(file)),
        conditionals=tuple(conditionals(file)),
        members=tuple(members(file)),
        test_cases=tuple(test_cases(file, vocabulary)),
    )


def syntax_errors(matches: Sequence[Match]) -> dict[str, int]:
    """The first line the parser could not read, per file that has one: an
    unreadable node's, or the line of a token the parser had to insert."""
    lines: dict[str, set[int]] = {}
    for m in matches:
        if m.fact == SYNTAX_ERROR:
            missing = m.captures.get(MISSING)
            lines.setdefault(m.path, set()).add(
                m.line if missing is None else missing.line
            )
    return {path: min(found) for path, found in lines.items()}


def merged(models: Sequence[CodeModel], **rest: object) -> CodeModel:
    """One CodeModel holding every fact of each, with the fields given in
    place of theirs."""
    joined: dict[str, object] = {
        f.name: tuple(fact for m in models for fact in getattr(m, f.name))
        for f in fields(CodeModel)
    }
    joined.update(rest)
    return CodeModel(**joined)  # type: ignore[arg-type]  # every field is a tuple


def passed(deadline: Deadline | None, now: float) -> bool:
    """Whether the deadline is already behind the time given."""
    return deadline is not None and deadline.epoch_seconds <= now


def readable(
    sources: Mapping[str, bytes],
) -> tuple[dict[str, bytes], list[Unparsed]]:
    """The sources inside the repository that are UTF-8, and why each other
    one is not read."""
    found: dict[str, bytes] = {}
    unreadable: list[Unparsed] = []
    for path in sorted(sources):
        if not stays_inside(path):
            unreadable.append(Unparsed(path=path, reason=LEAVES))
            continue
        try:
            sources[path].decode("utf-8")
        except UnicodeDecodeError as error:
            unreadable.append(Unparsed(path=path, reason=f"not utf-8: {error}"))
            continue
        found[path] = sources[path]
    return found, unreadable


def regions_of(
    sources: Mapping[str, bytes], declaration: Declaration, vocabulary: Vocabulary
) -> tuple[tuple[Region, ...], tuple[Region, ...]]:
    """The declaration's line regions of the files handed over, and the
    regions their section markers open."""
    declared = tuple(r for r in declaration.layers.regions if r.path in sources)
    found = tuple(
        region
        for path in declaration.layers.marker_files
        if path in sources
        for region in marker_regions(
            path, sources[path].decode("utf-8", "replace"), vocabulary
        )
    )
    return declared, found


def file_models(
    parsed: Mapping[str, bytes],
    matches: Sequence[Match],
    declaration: Declaration,
    regions: Sequence[Region],
    vocabulary: Vocabulary,
) -> tuple[list[CodeModel], list[Unparsed]]:
    """Each parsed file's facts, and the files nested past the walk."""
    by_path: dict[str, list[Match]] = {path: [] for path in parsed}
    for match in matches:
        if match.path in by_path:
            by_path[match.path].append(match)
    files: list[CodeModel] = []
    deep: list[Unparsed] = []
    for path in sorted(parsed):
        try:
            files.append(
                file_model(
                    path, parsed[path], by_path[path], declaration, regions, vocabulary
                )
            )
        except RecursionError:
            deep.append(Unparsed(path=path, reason=NESTED_TOO_DEEPLY))
    return files, deep


# --- Effectful helpers -------------------------------------------------------


def write_tree(tree: Path, sources: Mapping[str, bytes]) -> None:
    """Copy the sources under tree; a path leaving it is refused, never
    written."""
    for path, data in sources.items():
        if not stays_inside(path):
            raise ValueError(f"{path} leaves the repository")
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
) -> tuple[list[Match], dict[str, str]]:
    """Every match of the grammar's rules over the sources, keyed by
    repository path, and why each file whose output does not decode is not
    read. Raises ScanFailed when ast-grep cannot answer in time."""
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
    return parse_stream(done.stdout.decode("utf-8", "replace"), "tree")


def structure(
    sources: Mapping[str, bytes],
    declaration: Declaration,
    vocabulary: Vocabulary,
    deadline: Deadline | None,
    *,
    grammar: Grammar,
    language: str,
    binary: Path,
    clock: Callable[[], float],
    unreadable: str = "not {language}: syntax error at line {line}",
    code: Callable[[str], bool] = lambda path: True,
) -> Scanned | TimedOut:
    """The structural pass of one language over the sources: unreadable
    files and files the grammar cannot parse are unparsed with the reason
    (unreadable, formatted with the language and the first line the
    grammar could not read), and ast-grep failing leaves every readable
    file unparsed; a readable source that is not code (by `code`) is
    neither scanned nor unparsed. TimedOut when the deadline passes first."""
    if passed(deadline, clock()):
        return TimedOut(f"model the {language} sources")
    found, unparsed = readable(sources)
    found = {path: data for path, data in found.items() if code(path)}
    try:
        matches, undecoded = scan(
            found, grammar, binary=binary, deadline=deadline, clock=clock
        )
    except ScanFailed as failure:
        if failure.timed_out:
            return TimedOut(str(failure))
        unparsed.extend(Unparsed(path=path, reason=str(failure)) for path in found)
        return Scanned(
            files=(),
            parsed={},
            unparsed=tuple(sorted(unparsed, key=lambda u: u.path)),
            regions=(),
        )
    declared, marked = regions_of(sources, declaration, vocabulary)
    errors = syntax_errors(matches)
    unparsed.extend(
        Unparsed(path=path, reason=reason) for path, reason in undecoded.items()
    )
    for path in undecoded:
        errors.pop(path, None)
    unparsed.extend(
        Unparsed(path=path, reason=unreadable.format(language=language, line=line))
        for path, line in sorted(errors.items())
    )
    parsed = {
        p: data for p, data in found.items() if p not in errors and p not in undecoded
    }
    files, deep = file_models(parsed, matches, declaration, marked, vocabulary)
    unparsed.extend(deep)
    deep_paths = {u.path for u in deep}
    return Scanned(
        files=tuple(files),
        parsed={p: data for p, data in parsed.items() if p not in deep_paths},
        unparsed=tuple(sorted(unparsed, key=lambda u: u.path)),
        regions=declared + marked,
    )
