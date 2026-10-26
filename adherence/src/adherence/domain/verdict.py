"""domain/verdict.py -- two Reports and a Change to a Verdict.

A change is judged by comparing its head's report with its base's, by
finding identity with paths resolved through the change's renames
(DESIGN.ARCH-ADHERENCE.md, Judging a change; ARCHITECTURE.ARCH-
ADHERENCE.md, Mechanism > Judging a change). A head finding absent from the
base is introduced; one present there is existing. A base finding absent
from the head is removed only where every unit it names is still covered
at the head and its check ran there and passed. The verdict is the first
of not run, lowered, inconclusive, raised and held that applies.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from adherence.domain.finding import Finding, Provenance
from adherence.domain.model import UnitKind
from adherence.domain.report import Report, Verdict
from adherence.domain.target import Change

# --- Constants ---------------------------------------------------------------

# Units a record names rather than the code: covered wherever their check ran.
RECORD_UNITS = frozenset({UnitKind.SEAM, UnitKind.BEHAVIOR})

# --- Values ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Head:
    """What the comparison reads of the head report: its findings' keys, the
    units it covers by path and symbol, and the checks that ran."""

    keys: frozenset[tuple[str, str]]
    covered: frozenset[tuple[str, str | None]]
    ran: frozenset[str]


# --- Predicates --------------------------------------------------------------


def _check_passed_on(finding: Finding, path: str, head: Report) -> bool:
    """Whether the finding's check ran at the head and nothing kept it from
    the head's path: no coverage of that check there or everywhere, and no
    coverage of the path itself."""
    name = finding.check.name
    return not any(
        (c.check == name and c.path in (None, path))
        or (c.check is None and c.path == path)
        for c in head.coverage
    )


def _is_removed(finding: Finding, change: Change, head: Report, seen: _Head) -> bool:
    """Whether a base finding is removed: absent at the head, on a unit the
    head still covers, by a check that ran there and passed."""
    path = change.at_head(finding.unit.path)
    if (finding.identity, path) in seen.keys:
        return False
    if finding.check.name not in seen.ran:
        return False
    covered = (
        finding.unit.kind in RECORD_UNITS or (path, finding.unit.symbol) in seen.covered
    )
    return covered and _check_passed_on(finding, path, head)


# --- Pure helpers ------------------------------------------------------------


def _key(finding: Finding) -> tuple[str, str]:
    """A head finding's comparison key: its identity and its path."""
    return finding.identity, finding.unit.path


def _seen(head: Report) -> _Head:
    return _Head(
        keys=frozenset(_key(f) for f in head.findings),
        covered=frozenset(
            (u.path, u.symbol) for u in head.units if u.layer is not None
        ),
        ran=frozenset(c.name for c in head.ran),
    )


def _verdict(introduced: bool, removed: bool) -> Verdict:
    if introduced:
        return Verdict.LOWERED
    if removed:
        return Verdict.RAISED
    return Verdict.HELD


def compared(base: Report, head: Report, change: Change) -> Report:
    """The change's report: the head's, each finding marked introduced or
    existing, the base findings it removed, and the verdict."""
    if head.not_run_reason is not None:
        return replace(head, verdict=Verdict.NOT_RUN, reasons=(head.not_run_reason,))
    known = frozenset((f.identity, change.at_head(f.unit.path)) for f in base.findings)
    marked = tuple(
        replace(
            f,
            provenance=(
                Provenance.EXISTING if _key(f) in known else Provenance.INTRODUCED
            ),
        )
        for f in head.findings
    )
    seen = _seen(head)
    removed = tuple(f for f in base.findings if _is_removed(f, change, head, seen))
    introduced = any(f.provenance is Provenance.INTRODUCED for f in marked)
    return replace(
        head,
        findings=marked,
        removed=removed,
        verdict=_verdict(introduced, bool(removed)),
    )
