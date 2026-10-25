"""adapters/ts_depcruise.py -- CodeModelPort for TypeScript and JavaScript.

Every structural fact comes from the shared ast-grep adapter's TypeScript
rules over the bytes the use case handed over; nothing in the sources is
imported or run (ARCHITECTURE.ARCH-ADHERENCE.md, Security mitigations).
JavaScript is read with the TSX grammar, which parses it and JSX alike.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from adherence.adapters.astgrep import (
    BINARY,
    Grammar,
    Match,
    definitions,
    scan,
)
from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import Declaration, layer_of, marker_regions
from adherence.domain.model import CodeModel, Region, Unit, UnitKind
from adherence.domain.parameters import Vocabulary
from adherence.domain.source import source_lines

# --- Constants ---------------------------------------------------------------

GRAMMAR = Grammar(
    rules="typescript.yml",
    languages={
        "TypeScript": (),
        "Tsx": ("*.js", "*.mjs", "*.cjs", "*.jsx"),
    },
)

# --- Helpers -----------------------------------------------------------------


def _passed(deadline: Deadline | None, now: float) -> bool:
    return deadline is not None and deadline.epoch_seconds <= now


def _file_unit(path: str, data: bytes, declaration: Declaration) -> Unit:
    lines = len(source_lines(data.decode("utf-8", "replace")))
    return Unit(path, UnitKind.FILE, None, 1, lines, layer_of(path, None, declaration))


def _file_model(
    path: str,
    data: bytes,
    matches: Sequence[Match],
    declaration: Declaration,
    regions: Sequence[Region],
) -> CodeModel:
    """Every fact of one file, as a CodeModel of that file alone."""
    found = definitions(path, matches, declaration, regions)
    return CodeModel(
        units=(_file_unit(path, data, declaration), *(d.unit for d in found)),
        definitions=tuple(found),
    )


# --- Adapter -----------------------------------------------------------------


class TypeScriptCodeModel:
    """CodeModelPort over TypeScript and JavaScript sources. The clock is the
    edge's own, read before each step and handed to each analyzer."""

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
            return TimedOut("model the TypeScript sources")
        matches = scan(
            sources,
            GRAMMAR,
            binary=self._ast_grep,
            deadline=deadline,
            clock=self._clock,
        )
        found = tuple(
            region
            for path in declaration.layers.marker_files
            if path in sources
            for region in marker_regions(
                path, sources[path].decode("utf-8", "replace"), vocabulary
            )
        )
        declared = tuple(r for r in declaration.layers.regions if r.path in sources)
        by_path: dict[str, list[Match]] = {path: [] for path in sources}
        for match in matches:
            by_path.setdefault(match.path, []).append(match)
        files = [
            _file_model(path, sources[path], by_path[path], declaration, found)
            for path in sorted(sources)
        ]
        return CodeModel(
            units=tuple(u for f in files for u in f.units),
            definitions=tuple(d for f in files for d in f.definitions),
            regions=declared + found,
        )
