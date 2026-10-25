"""domain/finding.py -- one check failing on one unit.

A Finding names the quality and check (and so its kind), the unit, the
layer at the offending location, what it names, and the evidence: the
location and at most the offending line (DESIGN.ARCH-ADHERENCE.md,
Findings and explanations; ARCHITECTURE.ARCH-ADHERENCE.md, Module map).
"""

from __future__ import annotations

from dataclasses import dataclass

from adherence.domain.model import Layer, Unit
from adherence.domain.qualities import Check, CheckKind

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
