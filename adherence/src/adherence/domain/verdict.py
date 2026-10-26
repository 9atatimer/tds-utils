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

import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field, replace

from adherence.domain.coverage import Coverage
from adherence.domain.declaration import is_declared_check
from adherence.domain.finding import Finding, Provenance
from adherence.domain.model import UnitKind
from adherence.domain.qualities import Quality
from adherence.domain.report import Report, Verdict
from adherence.domain.target import Change

# --- Constants ---------------------------------------------------------------

# Units a record names rather than the code: covered wherever their check ran.
RECORD_UNITS = frozenset({UnitKind.SEAM, UnitKind.BEHAVIOR, UnitKind.TERM})

UnitKey = tuple[str, str | None]
FindingKey = tuple[str, str]

# --- Values ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Joins:
    """How the head names what the base named: files through the change's
    renames, and definitions through their renames -- a head definition
    whose body digest is that of exactly one base definition that
    disappeared, and no other's. `definitions` maps the head's (path,
    symbol) to the base's, its path already as the head names it."""

    change: Change
    definitions: Mapping[tuple[str, str], tuple[str, str]] = field(default_factory=dict)

    def base_key(self, finding: Finding) -> FindingKey:
        """A base finding's comparison key: its identity and its path as the
        head names it."""
        return finding.identity, self.change.at_head(finding.unit.path)

    def head_key(self, finding: Finding) -> FindingKey:
        """A head finding's comparison key: on a renamed definition, the
        identity its evidence has under the old name, and the old path."""
        unit = finding.unit
        was = self.definitions.get((unit.path, unit.symbol or ""))
        if was is None or unit.symbol is None:
            return finding.identity, unit.path
        text = re.sub(
            rf"\b{re.escape(_short(unit.symbol))}\b",
            _short(was[1]),
            finding.evidence.text,
        )
        joined = replace(finding, evidence=replace(finding.evidence, text=text))
        return joined.identity, was[0]

    def unit_at_head(self, finding: Finding) -> UnitKey:
        """The head's (path, symbol) for a base finding's unit."""
        path = self.change.at_head(finding.unit.path)
        symbol = finding.unit.symbol
        renamed = next(
            (now for now, was in self.definitions.items() if was == (path, symbol)),
            None,
        )
        return renamed if renamed is not None else (path, symbol)


@dataclass(frozen=True, slots=True)
class _Head:
    """What the comparison reads of the head report: its findings' keys, the
    units it covers by path and symbol, and the checks that ran."""

    keys: frozenset[FindingKey]
    covered: frozenset[UnitKey]
    ran: frozenset[str]


# --- Predicates --------------------------------------------------------------


def _check_passed_on(finding: Finding, path: str, head: Report) -> bool:
    """Whether nothing kept the finding's check from the head's path: no
    coverage of that check there or everywhere, and no coverage of the path
    itself."""
    name = finding.check.name
    return not any(
        (c.check == name and c.path in (None, path))
        or (c.check is None and c.path == path)
        for c in head.coverage
    )


def _is_removed(finding: Finding, joins: _Joins, head: Report, seen: _Head) -> bool:
    """Whether a base finding is removed: absent at the head, on a unit the
    head still covers, by a check that ran there and passed."""
    if joins.base_key(finding) in seen.keys:
        return False
    if finding.check.name not in seen.ran:
        return False
    unit = joins.unit_at_head(finding)
    covered = finding.unit.kind in RECORD_UNITS or unit in seen.covered
    return covered and _check_passed_on(finding, unit[0], head)


# --- Pure helpers ------------------------------------------------------------


def _short(symbol: str) -> str:
    """A qualified symbol's own name: `neat` of `Rules.neat`."""
    return symbol.rpartition(".")[2]


def definition_renames(
    *, base: Report, head: Report, change: Change
) -> dict[tuple[str, str], tuple[str, str]]:
    """Each head definition paired with the base definition it was renamed
    from, by a body digest that one definition lost and one gained."""
    before = {(change.at_head(b.path), b.symbol): b.digest for b in base.bodies}
    after = {(b.path, b.symbol): b.digest for b in head.bodies}
    gone: defaultdict[str, list[tuple[str, str]]] = defaultdict(list)
    come: defaultdict[str, list[tuple[str, str]]] = defaultdict(list)
    for key, digest in before.items():
        if key not in after:
            gone[digest].append(key)
    for key, digest in after.items():
        if key not in before:
            come[digest].append(key)
    return {
        news[0]: olds[0]
        for digest, news in come.items()
        if len(news) == 1 and len(olds := gone.get(digest, [])) == 1
    }


def _seen(head: Report, joins: _Joins) -> _Head:
    return _Head(
        keys=frozenset(joins.head_key(f) for f in head.findings),
        covered=frozenset(
            (u.path, u.symbol) for u in head.units if u.layer is not None
        ),
        ran=frozenset(c.name for c in head.ran),
    )


def _shown(coverage: Coverage) -> str:
    where = f" on {coverage.path}" if coverage.path else ""
    return f"{coverage.check} did not run{where}: {coverage.reason}"


def _inconclusive(base: Report, head: Report, change: Change) -> tuple[str, ...]:
    """Why the change is inconclusive: a check that could not run on a unit
    the change touched, or a check in coverage at the head that was not, for
    that reason, at the base. A change-level check never runs at a base, so
    only its coverage on a touched unit counts."""
    touched = change.touched()
    before = {
        replace(c, path=change.at_head(c.path) if c.path else None)
        for c in base.coverage
    }
    return tuple(
        _shown(c)
        for c in head.coverage
        if c.check is not None
        and (c.path in touched or (c not in before and not is_declared_check(c.check)))
    )


def _verdict(introduced: bool, inconclusive: bool, removed: bool) -> Verdict:
    if introduced:
        return Verdict.LOWERED
    if inconclusive:
        return Verdict.INCONCLUSIVE
    if removed:
        return Verdict.RAISED
    return Verdict.HELD


def _uncompared(base_reason: str, head: Report) -> Report:
    """The change's report when the base could not be measured under the
    head's identity: nothing is compared, so only a change-level finding,
    which no base ever holds, is introduced; the rest have no provenance."""
    marked = tuple(
        replace(f, provenance=Provenance.INTRODUCED)
        if f.check.quality is Quality.DECLARED and f.exempt is None
        else f
        for f in head.findings
    )
    introduced = any(f.provenance is Provenance.INTRODUCED for f in marked)
    return replace(
        head,
        findings=marked,
        verdict=Verdict.LOWERED if introduced else Verdict.INCONCLUSIVE,
        reasons=(base_reason,),
    )


def compared(*, base: Report, head: Report, change: Change) -> Report:
    """The change's report: the head's, each finding marked introduced or
    existing, the base findings it removed, and the verdict."""
    if head.not_run_reason is not None:
        return replace(head, verdict=Verdict.NOT_RUN, reasons=(head.not_run_reason,))
    if base.not_run_reason is not None:
        return _uncompared(base.not_run_reason, head)
    joins = _Joins(change, definition_renames(base=base, head=head, change=change))
    # A change-level finding belongs to the change that had it: a base kept
    # as some earlier change's report holds its own, which this one never
    # compares against.
    known_flaws = tuple(
        f for f in base.findings if f.check.quality is not Quality.DECLARED
    )
    # An exempt finding counts as neither introduced nor removed.
    removable = tuple(f for f in known_flaws if f.exempt is None)
    known = frozenset(joins.base_key(f) for f in known_flaws)
    marked = tuple(
        f
        if f.exempt is not None
        else replace(
            f,
            provenance=(
                Provenance.EXISTING
                if joins.head_key(f) in known
                else Provenance.INTRODUCED
            ),
        )
        for f in head.findings
    )
    seen = _seen(head, joins)
    removed = tuple(f for f in removable if _is_removed(f, joins, head, seen))
    introduced = any(f.provenance is Provenance.INTRODUCED for f in marked)
    reasons = _inconclusive(base, head, change)
    return replace(
        head,
        findings=marked,
        removed=removed,
        verdict=_verdict(introduced, bool(reasons), bool(removed)),
        reasons=reasons,
    )
