"""domain/checks/declared.py -- the Declared quality's change-level checks,
and the declaration-edit notices.

Covered: every unit the change creates is in a declared layer, by the
declaration in force or by the change's own widening. Record kept: no
design behavior and no Domain Language term is removed from an approved
record (DESIGN.ARCH-ADHERENCE.md, The Qualities table). Both run when a
change is judged: Covered over the head's units and the units the change
created, Record kept over the base's and the head's records
(ARCHITECTURE.ARCH-ADHERENCE.md, Mechanism > Measurement). Every edit of
the change's own declaration it is not judged under is a notice (Module
map).
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import replace

from adherence.domain.checks.outcome import CheckOutcome, undeclared
from adherence.domain.coverage import Coverage
from adherence.domain.declaration import (
    Declaration,
    DeclarationUnreadable,
    exemption_target,
    layer_of,
)
from adherence.domain.finding import Evidence, Finding, Notice
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
    base there is nothing to keep, and the check is coverage; so it is when
    the head's record could not be read, since what it states is unknown
    and nothing can be said removed."""
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
    if isinstance(head, RecordsUnavailable) and head.unread:
        return CheckOutcome(
            coverage=(
                Coverage(
                    f"the record at the head cannot be read: {head.reason}",
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


def _relayered(
    *, in_force: Declaration, proposed: Declaration, paths: Collection[str]
) -> list[str]:
    """The paths the proposed declaration puts in another layer than the
    one in force does, by assignment, region or marker file."""
    moved = [
        p
        for p in sorted(paths)
        if layer_of(p, None, proposed) != layer_of(p, None, in_force)
    ]
    regions = {
        r.path for r in set(proposed.layers.regions) ^ set(in_force.layers.regions)
    }
    markers = set(proposed.layers.marker_files) ^ set(in_force.layers.marker_files)
    return sorted({*moved, *regions, *markers})


def edit_notices(
    *,
    in_force: Declaration,
    proposed: Declaration | DeclarationUnreadable,
    paths: Collection[str],
    created: Collection[str],
) -> tuple[Notice, ...]:
    """A notice per edit the change's own declaration makes that it is not
    judged under: everything but its widening for the files it created
    (`paths` are the head's files). Each takes effect from the next change;
    an exemption it adds is inert for this one."""
    if isinstance(proposed, DeclarationUnreadable):
        return (
            Notice(
                f"the change's own declaration cannot be read: {proposed.reason}; "
                "it is judged under the declaration in force"
            ),
        )
    if proposed == in_force:
        return ()
    notices: list[Notice] = []
    relayered = [
        p
        for p in _relayered(in_force=in_force, proposed=proposed, paths=paths)
        if p not in created
    ]
    if relayered:
        notices.append(
            Notice(
                f"[layers] edited for {len(relayered)} existing path(s), first "
                f"{relayered[0]}: not judged under for this change; it takes "
                "effect from the next change"
            )
        )
    notices.extend(
        Notice(
            f"exemption added, inert for this change: {exemption_target(e)}: {e.reason}"
        )
        for e in proposed.exemptions
        if e not in in_force.exemptions
    )
    notices.extend(
        Notice(
            f"exemption removed: {exemption_target(e)}; "
            "it takes effect from the next change"
        )
        for e in in_force.exemptions
        if e not in proposed.exemptions
    )
    notices.extend(
        Notice(
            f"[{table}] edited: not judged under for this change; it takes "
            "effect from the next change"
        )
        for table, mine, theirs in (
            ("records", proposed.records, in_force.records),
            ("radar", proposed.radar, in_force.radar),
            ("runtimes", proposed.runtimes, in_force.runtimes),
            ("vocabulary", proposed.vocabulary, in_force.vocabulary),
        )
        if mine != theirs
    )
    return tuple(notices)
