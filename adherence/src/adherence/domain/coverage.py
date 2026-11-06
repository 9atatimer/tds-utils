"""domain/coverage.py -- every unit and check a run did not perform, and why.

The absence of findings is never adherence: what was unread, unanalyzed,
unanswered or cut off by TimedOut is Coverage with its reason
(DESIGN.ARCH-ADHERENCE.md, G4; ARCHITECTURE.ARCH-ADHERENCE.md, Mechanism >
Measurement).
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

from adherence.domain.model import CodeLanguage, CodeModel, UnitKind, language_of

# --- Constants ---------------------------------------------------------------

UNASSIGNED = "in no declared layer, so no check reads it"

# --- Values ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Coverage:
    """A check, a source, or a check on a source, that did not run, and why.
    `subject` names the unit on the source the check was to read, as its
    finding would name it, when the check was to read one unit there; the
    reason then says only why, so coverage counts by reason."""

    reason: str
    check: str | None = None
    path: str | None = None
    subject: str | None = None

    @property
    def why(self) -> str:
        """The reason, after the unit it is on when it names one."""
        return f"{self.subject}: {self.reason}" if self.subject else self.reason


# --- Pure helpers ------------------------------------------------------------


def unmodelled(model: CodeModel, *, declared: bool) -> tuple[Coverage, ...]:
    """The sources the analyzer could not read, and, for a declared
    repository, the files no declared layer or region covers. Only whether
    the repository is declared is read, so coverage, which the declaration's
    questions make, never imports the declaration."""
    covered = {u.path for u in model.units if u.layer is not None}
    files = sorted({u.path for u in model.units if u.kind is UnitKind.FILE})
    return (
        *(Coverage(u.reason, path=u.path) for u in model.unparsed),
        *(
            Coverage(UNASSIGNED, path=path)
            for path in files
            if declared and path not in covered
        ),
    )


def unmeasured(
    paths: Collection[str], measured: Collection[CodeLanguage]
) -> tuple[Coverage, ...]:
    """Every source in a language no bound analyzer measures, naming it."""
    names = {language.value for language in measured}
    return tuple(
        unmeasured_in(language, path)
        for path in sorted(paths)
        if (language := language_of(path)) is not None and language not in names
    )


def unmeasured_in(language: str, path: str) -> Coverage:
    """A source in a language no bound analyzer measures, naming it."""
    return Coverage(f"{language}: no analyzer measures this language", path=path)


def unread_script(interpreter: str, path: str) -> Coverage:
    """A script with no extension for an interpreter no analyzer reads one
    for (ARCHITECTURE.ARCH-ADHERENCE.md, Key Decisions, a shell script by
    its shebang)."""
    return Coverage(
        f"a {interpreter} script with no extension: no analyzer reads it", path=path
    )
