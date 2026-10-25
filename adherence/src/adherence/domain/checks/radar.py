"""domain/checks/radar.py -- every dependency is one the radar allows.

The rule checks of the Radar-true quality: Dependency and Edge only
(DESIGN.ARCH-ADHERENCE.md, The Qualities table: Radar-true), each a pure
function over the CodeModel and the Radar the declaration names. A
dependency is an import that resolves to no source of the repository and
is not the language's standard library; it is matched to a radar entry by
its package's name, case and separators aside.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from adherence.domain.checks.outcome import CheckOutcome, undeclared
from adherence.domain.coverage import Coverage
from adherence.domain.declaration import Declaration, layer_of
from adherence.domain.finding import Evidence, Finding
from adherence.domain.model import CodeModel, ImportEdge, Layer
from adherence.domain.parameters import Parameters, Vocabulary
from adherence.domain.qualities import catalog_check
from adherence.domain.records import Radar, RadarEntry, RecordsUnavailable, Ring

# --- Constants ---------------------------------------------------------------

DEPENDENCY = catalog_check("Dependency")
ALLOWED = frozenset({Ring.ADOPT, Ring.TRIAL})
SEPARATORS = re.compile(r"[-_.\s]+")

# --- Values ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Use:
    """One import of a dependency in a covered unit: the edge, its layer,
    the package's name and the radar's entry for it, if any."""

    edge: ImportEdge
    layer: Layer | None
    package: str
    entry: RadarEntry | None


# --- Pure helpers ------------------------------------------------------------


def comparable(name: str) -> str:
    """A package or radar name as the two are compared: lower case, every
    run of separators one hyphen."""
    return SEPARATORS.sub("-", name.strip().lower())


def package_of(edge: ImportEdge, vocabulary: Vocabulary) -> str | None:
    """The package an import is a dependency on; None for the repository's
    own modules and the standard library."""
    if edge.imported_path is not None:
        return None
    top = edge.imported.split(".")[0]
    if not top or top in vocabulary.standard_library:
        return None
    return vocabulary.packages.get(top, top)


def _uses(
    model: CodeModel, declaration: Declaration, radar: Radar, vocabulary: Vocabulary
) -> list[_Use]:
    """Every import of a dependency in a covered unit, with its radar entry."""
    entries = {comparable(e.name): e for e in radar.entries}
    uses: list[_Use] = []
    for edge in model.imports:
        package = package_of(edge, vocabulary)
        layer = layer_of(edge.path, edge.line, declaration, model.regions)
        if package is None or layer is None:
            continue
        uses.append(_Use(edge, layer, package, entries.get(comparable(package))))
    return uses


def _finding(model: CodeModel, use: _Use, subject: str) -> Finding | None:
    unit = model.unit_at(use.edge.path, use.edge.line)
    if unit is None:
        return None
    evidence = Evidence(use.edge.path, use.edge.line, use.edge.text)
    return Finding(DEPENDENCY, unit, use.layer, subject, evidence)


def _radar_or_coverage(
    check: str, declaration: Declaration, radar: Radar | RecordsUnavailable
) -> Radar | CheckOutcome:
    if not declaration.declared:
        return undeclared(check)
    if isinstance(radar, RecordsUnavailable):
        return CheckOutcome(coverage=(Coverage(radar.reason, check=check),), ran=False)
    return radar


def dependency(
    model: CodeModel,
    declaration: Declaration,
    radar: Radar | RecordsUnavailable,
    parameters: Parameters,
) -> CheckOutcome:
    """Every dependency a covered unit imports is on Adopt or Trial of the
    radar the repository names. Which of them a change introduced is
    provenance, decided when the change is judged."""
    read = _radar_or_coverage(DEPENDENCY.name, declaration, radar)
    if isinstance(read, CheckOutcome):
        return read
    findings: list[Finding] = []
    for use in _uses(model, declaration, read, parameters.vocabulary):
        if use.entry is None:
            subject = f"{use.package}: not on the radar"
        elif use.entry.ring not in ALLOWED:
            subject = f"{use.package}: on {use.entry.ring.value}"
        else:
            continue
        finding = _finding(model, use, subject)
        if finding is not None:
            findings.append(finding)
    return CheckOutcome(tuple(findings))
