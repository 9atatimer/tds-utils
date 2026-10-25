"""domain/finding.py -- one check failing on one unit.

A Notice is what a reviewer should see that is not a finding: a refused
exemption, a declaration edit, a report not kept; it never moves a
verdict. A Finding names the quality and check (and so its kind), the unit, the
layer at the offending location, what it names, and the evidence: the
location and at most the offending line (DESIGN.ARCH-ADHERENCE.md,
Findings and explanations; ARCHITECTURE.ARCH-ADHERENCE.md, Module map).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from adherence.domain.model import Layer, Unit
from adherence.domain.qualities import Check, CheckKind
from adherence.domain.source import source_lines

# --- Values ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Evidence:
    """The location of a flaw and at most its offending line."""

    path: str
    line: int
    text: str


@dataclass(frozen=True, slots=True)
class Finding:
    """One check failing on one unit. `subject` is what the finding names
    (the vendor, the cycle, the port, the seam); `reached` is the layer a
    layer finding reached, when it reached one."""

    check: Check
    unit: Unit
    layer: Layer | None
    subject: str
    evidence: Evidence
    reached: Layer | None = None
    kind: CheckKind = CheckKind.RULE


@dataclass(frozen=True, slots=True)
class Notice:
    """Something a reviewer should see that is not a finding."""

    message: str


# --- Pure helpers ------------------------------------------------------------


def _offending_line(evidence: Evidence, sources: Mapping[str, bytes]) -> str:
    """The source line the evidence locates, or the first line of the check's
    own text when the location is not a source line (a record's row)."""
    data = sources.get(evidence.path)
    lines = source_lines(data.decode("utf-8", "replace")) if data is not None else []
    if not 1 <= evidence.line <= len(lines):
        return next(iter(source_lines(evidence.text)), "")
    return lines[evidence.line - 1]


def quoted(
    findings: tuple[Finding, ...], sources: Mapping[str, bytes], bound: int
) -> tuple[Finding, ...]:
    """Each finding with its evidence set to the offending line, stripped and
    cut at the evidence bound: never more of the unit than that one line."""
    return tuple(
        replace(
            f,
            evidence=replace(
                f.evidence,
                text=_offending_line(f.evidence, sources).strip()[:bound],
            ),
        )
        for f in findings
    )
