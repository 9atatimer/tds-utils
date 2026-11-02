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
    ScanFailed,
    file_models,
    merged,
    readable_sources,
    regions_of,
    scan,
    syntax_errors,
)
from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import Declaration
from adherence.domain.model import CodeModel, Unparsed
from adherence.domain.parameters import Vocabulary

# --- Constants ---------------------------------------------------------------

GRAMMAR = Grammar(rules="bash.yml", languages={"Bash": ()})
# The Bash grammar is not the shell: it has no rule for zsh's own syntax
# and none for some Bash a shell accepts (a backgrounded here-document), so
# a file it cannot read is coverage that names where it stopped, never a
# claim that the file is broken.
UNREADABLE = "the Bash grammar cannot read it from line {line}"

# --- Pure helpers ------------------------------------------------------------


def _passed(deadline: Deadline | None, now: float) -> bool:
    return deadline is not None and deadline.epoch_seconds <= now


# --- Adapter -----------------------------------------------------------------


class ShellCodeModel:
    """CodeModelPort over shell sources. The clock is the edge's own, read
    before the scan and handed to it."""

    def __init__(
        self,
        *,
        ast_grep: Path = BINARY,
        clock: Callable[[], float] = time.time,
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
        if _passed(deadline, self._clock()):
            return TimedOut("model the shell sources")
        readable, unparsed = readable_sources(sources)
        try:
            matches = scan(
                readable,
                GRAMMAR,
                binary=self._ast_grep,
                deadline=deadline,
                clock=self._clock,
            )
        except ScanFailed as failure:
            if failure.timed_out:
                return TimedOut(str(failure))
            unparsed.extend(
                Unparsed(path=path, reason=str(failure)) for path in readable
            )
            return CodeModel(unparsed=tuple(sorted(unparsed, key=lambda u: u.path)))
        declared, found = regions_of(sources, declaration, vocabulary)
        errors = syntax_errors(matches)
        unparsed.extend(
            Unparsed(path=path, reason=UNREADABLE.format(line=line))
            for path, line in sorted(errors.items())
        )
        parsed = {p: data for p, data in readable.items() if p not in errors}
        files, deep = file_models(parsed, matches, declaration, found, vocabulary)
        unparsed.extend(deep)
        return merged(
            files,
            regions=declared + found,
            unparsed=tuple(sorted(unparsed, key=lambda u: u.path)),
        )
