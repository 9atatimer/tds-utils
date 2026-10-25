"""adapters/shell_astgrep.py -- CodeModelPort for shell.

Regions, bodies and dependencies come from the shared ast-grep adapter's
Bash rules (ARCHITECTURE.ARCH-ADHERENCE.md, Module map:
adapters/shell_astgrep.py); zsh is read with the same grammar. Every file
handed over is read as shell: which files are shell is the caller's to
say. A script's dependencies are the tools it runs, by name or through
`command` and `exec`: one import edge per tool per file, at its first use,
never a builtin or a function the sources define.

ast-grep runs as a subprocess over a copy of the sources in a scratch
directory, never the repository, with an allowlisted environment and the
time left before the deadline as its bound. Nothing in the sources is run
(Security mitigations).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from adherence.adapters.astgrep import BINARY, Grammar, merged, structure
from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import Declaration
from adherence.domain.model import CodeModel, ImportEdge
from adherence.domain.parameters import Vocabulary

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

# --- Pure helpers ------------------------------------------------------------


def is_tool(command: str, functions: frozenset[str]) -> bool:
    """Whether a command run by name is a tool the script requires: not a
    builtin, not a function the sources define, and not a path to a file."""
    return command not in BUILTINS and command not in functions and "/" not in command


def dependencies(
    edges: Sequence[ImportEdge], functions: frozenset[str]
) -> tuple[ImportEdge, ...]:
    """The tools each file requires, each once, at its first use."""
    seen: set[tuple[str, str]] = set()
    found: list[ImportEdge] = []
    for edge in sorted(edges, key=lambda e: (e.path, e.line)):
        key = (edge.path, edge.imported)
        if key in seen or not is_tool(edge.imported, functions):
            continue
        seen.add(key)
        found.append(edge)
    return tuple(found)


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
        functions = frozenset(
            d.unit.symbol
            for f in scanned.files
            for d in f.definitions
            if d.unit.symbol is not None
        )
        return merged(
            scanned.files,
            imports=dependencies(
                [edge for f in scanned.files for edge in f.imports], functions
            ),
            regions=scanned.regions,
            unparsed=scanned.unparsed,
        )
