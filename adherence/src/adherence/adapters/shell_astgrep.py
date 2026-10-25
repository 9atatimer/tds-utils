"""adapters/shell_astgrep.py -- CodeModelPort for shell.

Regions, bodies and dependencies come from the shared ast-grep adapter's
Bash rules (ARCHITECTURE.ARCH-ADHERENCE.md, Module map:
adapters/shell_astgrep.py); zsh is read with the same grammar. Every file
handed over is read as shell: which files are shell is the caller's to
say.

A script's dependencies are the tools it runs, by name or through
`command` and `exec`: one import edge per tool per file, at its first use,
never a builtin or a function the sources define. A file it sources is an
edge to that file when the file is one of the sources; a file sourced from
outside them is a path on the machine, not a tool, and no edge.

ast-grep runs as a subprocess over a copy of the sources in a scratch
directory, never the repository, with an allowlisted environment and the
time left before the deadline as its bound. Nothing in the sources is run
(Security mitigations).
"""

from __future__ import annotations

import posixpath
import re
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from adherence.adapters.astgrep import BINARY, Grammar, Scanned, merged, structure
from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import Declaration
from adherence.domain.model import Call, CodeModel, ImportEdge
from adherence.domain.parameters import Vocabulary
from adherence.domain.source import source_lines

# --- Constants ---------------------------------------------------------------

# Every file handed over is shell, whatever its name.
GRAMMAR = Grammar(rules="bash.yml", languages={"Bash": ("*",)})
# What the shell itself runs, bash's, zsh's and POSIX's builtins and
# reserved words: never a tool a script requires.
BUILTINS = frozenset(
    {
        ".", ":", "[", "[[", "alias", "autoload", "bg", "bind", "bindkey",
        "break", "builtin", "caller", "cd", "command", "compgen", "complete",
        "compopt", "continue", "coproc", "declare", "dirs", "disown", "echo",
        "emulate", "enable", "eval", "exec", "exit", "export", "false", "fc",
        "fg", "float", "functions", "getopts", "hash", "help", "history",
        "integer", "jobs", "kill", "let", "local", "logout", "mapfile",
        "noglob", "popd", "print", "printf", "pushd", "pwd", "read",
        "readarray", "readonly", "rehash", "return", "set", "setopt", "shift",
        "shopt", "source", "suspend", "test", "time", "times", "trap", "true",
        "type", "typeset", "ulimit", "umask", "unalias", "unset", "unsetopt",
        "vared", "wait", "whence", "zle", "zmodload", "zparseopts", "zstyle",
    }
)  # fmt: skip
# A command named as a tool is: no path, no expansion, no quoting.
PLAIN_NAME = re.compile(r"[\w.+-]+")
# Where an expansion, a substitution or a quote ends; a sourced path's
# literal tail follows the last of them.
EXPANSION_END = re.compile(r"[$`})\"']")
QUOTES = ("'", '"')

# --- Predicates --------------------------------------------------------------


def is_tool(command: str, functions: frozenset[str]) -> bool:
    """Whether a command run by name is a tool the script requires: a plain
    name, not a builtin, and not a function the sources define."""
    return (
        PLAIN_NAME.fullmatch(command) is not None
        and command not in BUILTINS
        and command not in functions
    )


# --- Pure helpers ------------------------------------------------------------


def unquoted(text: str) -> str:
    """A word as written without the one pair of quotes around it."""
    if len(text) >= 2 and text[0] == text[-1] and text[0] in QUOTES:
        return text[1:-1]
    return text


def sourced_path(script: str, written: str, sources: Collection[str]) -> str | None:
    """The source a script's `source` reads, or None when it is none of
    them: a literal path from the script's directory or else the root; a
    path built by an expansion by its literal tail, when exactly one
    source ends with it."""
    if not EXPANSION_END.search(written):
        for base in (posixpath.dirname(script), ""):
            candidate = posixpath.normpath(posixpath.join(base, written))
            if candidate in sources:
                return candidate
        return None
    tail = EXPANSION_END.split(written)[-1]
    parts = [part for part in tail.split("/") if part not in ("", ".", "..")]
    if not parts or tail.endswith("/"):
        return None
    wanted = "/".join(parts)
    found = [p for p in sources if p == wanted or p.endswith(f"/{wanted}")]
    return found[0] if len(found) == 1 else None


def sourced(edges: Sequence[ImportEdge], sources: Collection[str]) -> list[ImportEdge]:
    """Each `source` of a file that is one of the sources, as an edge to it
    with the path as written."""
    found: list[ImportEdge] = []
    for edge in edges:
        written = unquoted(edge.imported)
        target = sourced_path(edge.path, written, sources)
        if target is not None:
            found.append(replace(edge, imported=written, imported_path=target))
    return found


def dependencies(
    calls: Sequence[Call],
    lines: Mapping[str, Sequence[str]],
    functions: frozenset[str],
) -> list[ImportEdge]:
    """The tools each file requires, each once, at its first use, with
    that line's text."""
    seen: set[tuple[str, str]] = set()
    found: list[ImportEdge] = []
    for call in sorted(calls, key=lambda c: (c.path, c.line)):
        key = (call.path, call.callee)
        if key in seen or not is_tool(call.callee, functions):
            continue
        seen.add(key)
        found.append(
            ImportEdge(
                path=call.path,
                imported=call.callee,
                line=call.line,
                text=lines[call.path][call.line - 1].strip(),
                imported_path=None,
            )
        )
    return found


def shell_model(scanned: Scanned) -> CodeModel:
    """The structural pass with its imports made a shell script's: the
    files it sources that are sources, and the tools it runs."""
    functions = frozenset(
        d.unit.symbol
        for f in scanned.files
        for d in f.definitions
        if d.unit.symbol is not None
    )
    lines = {
        path: source_lines(data.decode("utf-8", "replace"))
        for path, data in scanned.parsed.items()
    }
    edges = sourced(
        [edge for f in scanned.files for edge in f.imports], scanned.parsed
    ) + dependencies([c for f in scanned.files for c in f.calls], lines, functions)
    return merged(
        scanned.files,
        imports=tuple(sorted(edges, key=lambda e: (e.path, e.line, e.imported))),
        regions=scanned.regions,
        unparsed=scanned.unparsed,
    )


# --- Adapter -----------------------------------------------------------------


class ShellCodeModel:
    """CodeModelPort over shell sources. The clock is the edge's own, read
    before the scan and handed to it."""

    def __init__(
        self, *, ast_grep: Path = BINARY, clock: Callable[[], float] = time.time
    ) -> None:
        self._ast_grep = ast_grep
        self._clock = clock

    def model(
        self,
        sources: Mapping[str, bytes],
        declaration: Declaration,
        vocabulary: Vocabulary,
        deadline: Deadline | None,
    ) -> CodeModel | TimedOut:
        scanned = structure(
            sources,
            declaration,
            vocabulary,
            deadline,
            grammar=GRAMMAR,
            language="shell",
            binary=self._ast_grep,
            clock=self._clock,
        )
        if isinstance(scanned, TimedOut):
            return scanned
        return shell_model(scanned)
