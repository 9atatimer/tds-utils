"""adapters/shell_astgrep.py -- CodeModelPort for shell.

Regions, bodies and dependencies come from the shared ast-grep adapter's
Bash rules (ARCHITECTURE.ARCH-ADHERENCE.md, Module map:
adapters/shell_astgrep.py); zsh is read with the same grammar. Every file
handed over is read as shell: which files are shell is the caller's to
say.

ast-grep runs as a subprocess over a copy of the sources in a scratch
directory, never the repository, with an allowlisted environment and the
time left before the deadline as its bound. Nothing in the sources is run
(Security mitigations).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from pathlib import Path

from adherence.adapters.astgrep import BINARY, Grammar, merged, structure
from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import Declaration
from adherence.domain.model import CodeModel
from adherence.domain.parameters import Vocabulary

# --- Constants ---------------------------------------------------------------

# Every file handed over is shell, whatever its name.
GRAMMAR = Grammar(rules="bash.yml", languages={"Bash": ("*",)})

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
        return merged(scanned.files, regions=scanned.regions, unparsed=scanned.unparsed)
