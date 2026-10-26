"""domain/checks/declared.py -- the Declared quality's change-level checks.

Covered: every unit the change creates is in a declared layer, by the
declaration in force or by the change's own widening. Record kept: no
design behavior and no Domain Language term is removed from an approved
record (DESIGN.ARCH-ADHERENCE.md, The Qualities table). Both run when a
change is judged: Covered over the head's units and the units the change
created, Record kept over the base's and the head's records
(ARCHITECTURE.ARCH-ADHERENCE.md, Mechanism > Measurement).
"""

from __future__ import annotations

from dataclasses import replace

from adherence.domain.checks.outcome import CheckOutcome, undeclared
from adherence.domain.coverage import Coverage
from adherence.domain.declaration import Declaration
from adherence.domain.finding import Evidence, Finding
from adherence.domain.model import Unit, UnitKind
from adherence.domain.qualities import Check, catalog_check
from adherence.domain.records import DesignRecords, RecordsUnavailable
from adherence.domain.report import Report
from adherence.domain.target import Change
from adherence.domain.verdict import definition_renames

# --- Constants ---------------------------------------------------------------

COVERED = catalog_check("Covered")
RECORD_KEPT = catalog_check("Record kept")

# --- Pure helpers ------------------------------------------------------------


def created_units(*, base: Report, head: Report, change: Change) -> tuple[Unit, ...]:
    """The units the change created: each file it created, and each
    definition in a file it kept that the base had under no name -- neither
    at its path and symbol nor as the definition it was renamed from. With
    no base report to read, only the files it created."""
    created = set(change.created)
    if base.not_run_reason is not None:
        return tuple(
            u for u in head.units if u.kind is UnitKind.FILE and u.path in created
        )
    before = {(change.at_head(u.path), u.symbol) for u in base.units}
    renamed = definition_renames(base=base, head=head, change=change)
    return tuple(
        u
        for u in head.units
        if (u.kind is UnitKind.FILE and u.path in created)
        or (
            u.kind is not UnitKind.FILE
            and u.path not in created
            and (u.path, u.symbol) not in before
            and (u.path, u.symbol or "") not in renamed
        )
    )


def covered(
    created: tuple[Unit, ...], declaration: Declaration, bound: int
) -> CheckOutcome:
    """A finding on every created unit no declared layer covers, naming it."""
    if not declaration.declared:
        return undeclared(COVERED.name)
    return CheckOutcome(
        tuple(
            Finding(
                COVERED,
                unit,
                None,
                unit.symbol or unit.path,
                Evidence(
                    unit.path,
                    unit.start,
                    f"{unit.kind.value} {unit.symbol or unit.path}"[:bound],
                ),
            )
            for unit in created
            if unit.layer is None
        )
    )


def _removed(
    *, path: str, kind: UnitKind, name: str, line: int, why: str, bound: int
) -> Finding:
    """The Record kept finding on one behavior or term the record lost."""
    unit = Unit(path, kind, name, line, line, None)
    return Finding(
        RECORD_KEPT, unit, None, name, Evidence(path, line, f"{why}: {name}"[:bound])
    )


def record_kept(
    *,
    base: DesignRecords | RecordsUnavailable,
    head: DesignRecords | RecordsUnavailable,
    bound: int,
) -> CheckOutcome:
    """A finding per design behavior and per Domain Language term the base's
    approved records state and the head's do not: every one of them, when
    the head has no approved record left. With no approved record at the
    base there is nothing to keep, and the check is coverage."""
    if isinstance(base, RecordsUnavailable):
        return CheckOutcome(
            coverage=(
                Coverage(
                    f"no approved record at the base: {base.reason}",
                    check=RECORD_KEPT.name,
                ),
            ),
            ran=False,
        )
    behaviors = (
        set()
        if isinstance(head, RecordsUnavailable)
        else {b.name for b in head.behaviors}
    )
    terms = (
        set()
        if isinstance(head, RecordsUnavailable)
        else {t.name for t in head.domain_language}
    )
    return CheckOutcome(
        (
            *(
                _removed(
                    path=b.path,
                    kind=UnitKind.BEHAVIOR,
                    name=b.name,
                    line=b.line,
                    why="behavior removed",
                    bound=bound,
                )
                for b in base.behaviors
                if b.name not in behaviors
            ),
            *(
                _removed(
                    path=t.path,
                    kind=UnitKind.TERM,
                    name=t.name,
                    line=t.line,
                    why="term removed",
                    bound=bound,
                )
                for t in base.domain_language
                if t.name not in terms
            ),
        )
    )


def with_outcome(report: Report, check: Check, outcome: CheckOutcome) -> Report:
    """The report with a change-level check's outcome in place of the
    coverage that said it runs only when a change is judged."""
    return replace(
        report,
        ran=(*report.ran, check) if outcome.ran else report.ran,
        findings=(*report.findings, *outcome.findings),
        coverage=(
            *(c for c in report.coverage if c.check != check.name),
            *outcome.coverage,
        ),
    )
