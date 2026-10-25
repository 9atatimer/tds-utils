"""adapters/ts_depcruise.py -- CodeModelPort for TypeScript and JavaScript.

Nothing in the sources is imported or run (ARCHITECTURE.ARCH-ADHERENCE.md,
Security mitigations).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping

from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import Declaration, layer_of
from adherence.domain.model import CodeModel, Unit, UnitKind
from adherence.domain.parameters import Vocabulary
from adherence.domain.source import source_lines

# --- Helpers -----------------------------------------------------------------


def _passed(deadline: Deadline | None, now: float) -> bool:
    return deadline is not None and deadline.epoch_seconds <= now


def _file_unit(path: str, data: bytes, declaration: Declaration) -> Unit:
    lines = len(source_lines(data.decode("utf-8", "replace")))
    return Unit(path, UnitKind.FILE, None, 1, lines, layer_of(path, None, declaration))


# --- Adapter -----------------------------------------------------------------


class TypeScriptCodeModel:
    """CodeModelPort over TypeScript and JavaScript sources. The clock is the
    edge's own, read before each step."""

    def __init__(self, *, clock: Callable[[], float] = time.time) -> None:
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
        return CodeModel(
            units=tuple(
                _file_unit(path, sources[path], declaration) for path in sorted(sources)
            )
        )
