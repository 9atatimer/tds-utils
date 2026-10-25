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
    Body,
    CodeModel,
    Definition,
    ImportEdge,
    Region,
    Unit,
    UnitKind,
)

# --- Constants ---------------------------------------------------------------

RULES = Path(__file__).resolve().parent / "astgrep_rules"
BINARY = Path(sys.executable).with_name("ast-grep")
IGNORE_FILES = ("hidden", "dot", "exclude", "global", "parent", "vcs")
FUNCTION, TYPE, IMPORT = "function", "type", "import"
NAME, SOURCE = "NAME", "SOURCE"

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


def definitions(
    path: str,
    matches: Sequence[Match],
    declaration: Declaration,
    regions: Sequence[Region],
) -> list[Definition]:
    """The definitions of one file, each in the layer of its first line."""
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
            signature=None,
            body=Body("", (), ()),
            bases=(),
            decorators=(),
            parent=d.parent,
            nested=False,
        )
        for d in _defined(matches)
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
