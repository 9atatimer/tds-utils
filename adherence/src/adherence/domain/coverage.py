"""domain/coverage.py -- every unit and check a run did not perform, and why.

The absence of findings is never adherence: what was unread, unanalyzed,
unanswered or cut off by TimedOut is Coverage with its reason
(DESIGN.ARCH-ADHERENCE.md, G4; ARCHITECTURE.ARCH-ADHERENCE.md, Mechanism >
Measurement).
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

from adherence.domain.declaration import Declaration
from adherence.domain.model import CodeLanguage, CodeModel, UnitKind, language_of

# --- Constants ---------------------------------------------------------------

UNASSIGNED = "in no declared layer, so no check reads it"

# --- Values ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Coverage:
    """A check, a source, or a check on a source, that did not run, and why."""

    reason: str
    check: str | None = None
    path: str | None = None


# --- Pure helpers ------------------------------------------------------------


def unmodelled(model: CodeModel, declaration: Declaration) -> tuple[Coverage, ...]:
    """The sources the analyzer could not read, and, for a declared
    repository, the files no declared layer or region covers."""
    covered = {u.path for u in model.units if u.layer is not None}
    files = sorted({u.path for u in model.units if u.kind is UnitKind.FILE})
    return (
        *(Coverage(u.reason, path=u.path) for u in model.unparsed),
        *(
            Coverage(UNASSIGNED, path=path)
            for path in files
            if declaration.declared and path not in covered
        ),
    )


def unmeasured(
    paths: Collection[str], measured: Collection[CodeLanguage]
) -> tuple[Coverage, ...]:
    """Every source in a language no bound analyzer measures, naming it."""
    names = {language.value for language in measured}
    return tuple(
        Coverage(f"{language}: no analyzer measures this language", path=path)
        for path in sorted(paths)
        if (language := language_of(path)) is not None and language not in names
    )
