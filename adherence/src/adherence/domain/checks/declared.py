"""domain/checks/declared.py -- the Declared quality's change-level checks.

Covered: every unit the change creates is in a declared layer, by the
declaration in force or by the change's own widening (DESIGN.ARCH-
ADHERENCE.md, The Qualities table). It runs when a change is judged, over
the head's units and the units the change created (ARCHITECTURE.ARCH-
ADHERENCE.md, Mechanism > Measurement).
"""

from __future__ import annotations

from dataclasses import replace

from adherence.domain.checks.outcome import CheckOutcome, undeclared
from adherence.domain.declaration import Declaration
from adherence.domain.finding import Evidence, Finding
from adherence.domain.model import Unit, UnitKind
from adherence.domain.qualities import Check, catalog_check
from adherence.domain.report import Report
from adherence.domain.target import Change
from adherence.domain.verdict import definition_renames

# --- Constants ---------------------------------------------------------------

COVERED = catalog_check("Covered")

# --- Pure helpers ------------------------------------------------------------


def created_units(base: Report, head: Report, change: Change) -> tuple[Unit, ...]:
    """The units the change created: each file it created, and each
    definition in a file it kept that the base had under no name -- neither
    at its path and symbol nor as the definition it was renamed from."""
    created = set(change.created)
    before = {(change.at_head(u.path), u.symbol) for u in base.units}
    renamed = definition_renames(base, head, change)
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
