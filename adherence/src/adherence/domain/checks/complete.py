"""domain/checks/complete.py -- the code does the work it claims to.

The rule checks of the Complete quality: Stub, Complexity and Duplication
(DESIGN.ARCH-ADHERENCE.md, The Qualities table: Complete), each a pure
function over the CodeModel. Done and Hand-rolled are judged questions
(task-064).
"""

from __future__ import annotations

from collections.abc import Sequence

from adherence.domain.checks.outcome import CheckOutcome, undeclared
from adherence.domain.coverage import Coverage
from adherence.domain.declaration import Declaration, layer_of
from adherence.domain.finding import Evidence, Finding
from adherence.domain.model import CodeModel, Definition, Layer, Unit, UnitKind
from adherence.domain.parameters import Parameters, Vocabulary
from adherence.domain.qualities import catalog_check
from adherence.domain.records import DesignRecords, RecordsUnavailable

# --- Constants ---------------------------------------------------------------

STUB = catalog_check("Stub")
COMPLEXITY = catalog_check("Complexity")
NO_CEILING = "no {} ceiling is supplied"

# --- Predicates --------------------------------------------------------------


def is_marked(names: Sequence[str], markers: frozenset[str]) -> bool:
    """Whether any name, by its full dotted form or its last part, is one of
    the markers."""
    return any(n in markers or n.rpartition(".")[2] in markers for n in names)


def is_declaration(
    definition: Definition, owner: Definition | None, vocabulary: Vocabulary
) -> bool:
    """Whether a function's placeholder body declares rather than stubs: it
    is in the ports layer, abstract, or a method of a protocol or abstract
    type."""
    return (
        definition.unit.layer is Layer.PORTS
        or is_marked(definition.decorators, vocabulary.abstract_markers)
        or (owner is not None and is_marked(owner.bases, vocabulary.abstract_markers))
    )


def is_checked(layer: Layer | None) -> bool:
    """Whether Stub reads a unit in this layer: covered, and not a test."""
    return layer is not None and layer is not Layer.TEST


# --- Pure helpers ------------------------------------------------------------


def _stub_findings(
    definition: Definition, owner: Definition | None, vocabulary: Vocabulary
) -> list[Finding]:
    """The finding on a placeholder body, and one per sleep standing in for
    work."""
    unit = definition.unit
    findings: list[Finding] = []
    if definition.body.stub_markers and not is_declaration(
        definition, owner, vocabulary
    ):
        marker = definition.body.stub_markers[0]
        findings.append(
            Finding(
                STUB, unit, unit.layer, marker, Evidence(unit.path, unit.start, marker)
            )
        )
    findings.extend(
        Finding(STUB, unit, unit.layer, "sleep", Evidence(unit.path, line, "sleep"))
        for line in definition.body.sleeps
    )
    return findings


def stub(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
) -> CheckOutcome:
    """No stub marker, placeholder body, or sleep standing in for work, in a
    non-test function."""
    if not declaration.declared:
        return undeclared(STUB.name)
    types = {
        (d.unit.path, d.unit.symbol): d
        for d in model.definitions
        if d.unit.kind is UnitKind.TYPE
    }
    findings: list[Finding] = []
    for d in model.definitions:
        if d.unit.kind is not UnitKind.FUNCTION or not is_checked(d.unit.layer):
            continue
        owner = types.get((d.unit.path, d.parent)) if d.parent else None
        findings.extend(_stub_findings(d, owner, parameters.vocabulary))
    return CheckOutcome(tuple(findings))


def _function_unit(
    model: CodeModel, path: str, symbol: str, line: int, layer: Layer | None
) -> Unit:
    """The model's unit for a function the tooling names, or one built from
    what the tooling reports when the analyzer has none."""
    named = next(
        (
            u
            for u in model.units
            if u.path == path and u.kind is UnitKind.FUNCTION and u.symbol == symbol
        ),
        None,
    )
    return named or Unit(path, UnitKind.FUNCTION, symbol, line, line, layer)


def complexity(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
) -> CheckOutcome:
    """No function over the complexity ceiling. Needs no declaration; a
    declared repository's uncovered functions are coverage, never checked."""
    ceiling = parameters.limits.complexity_ceiling
    if ceiling is None:
        reason = NO_CEILING.format("complexity")
        return CheckOutcome(
            coverage=(Coverage(reason, check=COMPLEXITY.name),), ran=False
        )
    findings: list[Finding] = []
    for measured in model.metrics.complexity:
        layer = layer_of(measured.path, measured.line, declaration, model.regions)
        if measured.value <= ceiling or (declaration.declared and layer is None):
            continue
        unit = _function_unit(
            model, measured.path, measured.symbol, measured.line, layer
        )
        subject = (
            f"{measured.symbol}: complexity {measured.value} over the ceiling {ceiling}"
        )
        findings.append(
            Finding(
                COMPLEXITY,
                unit,
                layer,
                subject,
                Evidence(measured.path, measured.line, measured.symbol),
            )
        )
    return CheckOutcome(tuple(findings))
