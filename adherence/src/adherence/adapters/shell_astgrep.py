"""adapters/shell_astgrep.py -- CodeModelPort for shell, over ast-grep.

Shell sources (sh, bash, zsh) read through the shared astgrep adapter
with its Bash grammar: each file and each function is a unit in its
layer, with the regions its `# --- Section ---` markers open, each
function's body, and every command it runs as a call
(ARCHITECTURE.ARCH-ADHERENCE.md, Module map: adapters/shell_astgrep.py).
Nothing else in the CodeModel is read from shell; the checks that need it
say so (domain/checks/run.py).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from pathlib import Path

from adherence.adapters.astgrep import (
    BINARY,
    Grammar,
    GrammarRead,
    Scanner,
    by_path,
    merged,
    read_through,
)
from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import Declaration
from adherence.domain.model import CodeModel
from adherence.domain.parameters import Vocabulary

# --- Constants ---------------------------------------------------------------

# The scan tree holds only the sources handed to this analyzer, so the
# grammar claims every file in it: a script found by its shebang has no
# extension for ast-grep to know it by (Issue#638), and would otherwise be
# skipped and read as a bare, clean file.
GRAMMAR = Grammar(rules="bash.yml", languages={"Bash": ("*",)})
# The Bash grammar is not the shell: it has no rule for zsh's own syntax
# and none for some Bash a shell accepts (a backgrounded here-document), so
# a file it cannot read is coverage that names where it stopped, never a
# claim that the file is broken.
UNREADABLE = "the Bash grammar cannot read it from line {line}"

# --- Pure helpers ------------------------------------------------------------


def _every_path(path: str) -> bool:
    """The grammar claims every file handed over (GRAMMAR)."""
    return True


def _unreadable(line: int) -> str:
    return UNREADABLE.format(line=line)


# --- Adapter -----------------------------------------------------------------


class ShellCodeModel:
    """CodeModelPort over shell sources. The clock is the edge's own, read
    before the scan and handed to it."""

    def __init__(
        self,
        *,
        ast_grep: Path = BINARY,
        bound: float | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._scanner = Scanner(ast_grep, bound, clock)

    def model(
        self,
        sources: Mapping[str, bytes],
        declaration: Declaration,
        vocabulary: Vocabulary,
        deadline: Deadline | None,
    ) -> CodeModel | TimedOut:
        read = read_through(
            sources,
            operation="model the shell sources",
            grammar=GRAMMAR,
            scanner=self._scanner,
            keep=_every_path,
            unreadable=_unreadable,
            declaration=declaration,
            vocabulary=vocabulary,
            deadline=deadline,
        )
        if not isinstance(read, GrammarRead):
            return read
        return merged(read.files, regions=read.regions, unparsed=by_path(read.unparsed))
