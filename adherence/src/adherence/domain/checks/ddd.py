"""domain/checks/ddd.py -- each concept named once, with one owner.

The rule parts of Language, Boundary and Anemic (DESIGN.ARCH-ADHERENCE.md,
The Qualities table: Domain-driven), each a pure function over the
CodeModel. Their judged parts -- same_concept, invariant_broken,
rules_elsewhere -- and the Decision question are asked by no judge in this
suite version; what they would be asked about is coverage.
"""

from __future__ import annotations

from collections.abc import Mapping

from adherence.domain.checks.outcome import CheckOutcome, undeclared
from adherence.domain.checks.roles import (
    annotation_names,
    by_symbol,
    is_within,
    short_name,
)
from adherence.domain.coverage import Coverage
from adherence.domain.declaration import Declaration, layer_of
from adherence.domain.finding import Evidence, Finding
from adherence.domain.model import (
    CodeModel,
    Definition,
    MemberKind,
    UnitKind,
    Write,
)
from adherence.domain.parameters import Parameters
from adherence.domain.qualities import catalog_check
from adherence.domain.records import DesignRecords, RecordsUnavailable

# --- Constants ---------------------------------------------------------------

BOUNDARY = catalog_check("Boundary")
NO_JUDGE = "no judged question is asked in this suite version"
BOUNDARY_JUDGED = (
    f"the judged part (invariant_broken: does the foreign write break an "
    f"invariant?) {NO_JUDGE}"
)

# --- Pure helpers ------------------------------------------------------------


def _types_by_name(model: CodeModel) -> dict[str, list[Definition]]:
    """Every type the model defines, by its name."""
    types: dict[str, list[Definition]] = {}
    for d in model.definitions:
        if d.unit.kind is UnitKind.TYPE:
            types.setdefault(short_name(d.unit.symbol), []).append(d)
    return types


def written_type(
    write: Write,
    definitions: Mapping[tuple[str, str], Definition],
    types: Mapping[str, list[Definition]],
    fields: frozenset[tuple[str, str, str]],
) -> Definition | None:
    """The type whose declared field a write assigns, when the object
    written is a parameter of the writer annotated with that type; None
    when the write cannot be pinned on a type."""
    writer = definitions.get((write.path, write.within or ""))
    if writer is None or writer.signature is None:
        return None
    parameter = next(
        (p for p in writer.signature.parameters if p.name == write.target), None
    )
    if parameter is None:
        return None
    return next(
        (
            t
            for name in annotation_names(parameter.annotation)
            for t in types.get(short_name(name), [])
            if (t.unit.path, t.unit.symbol or "", write.field) in fields
        ),
        None,
    )


def boundary(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
) -> CheckOutcome:
    """No value type has a field written outside its owning unit, the type
    itself. The rule part reads a write whose object is a parameter of the
    writer annotated with the type; the judged part is coverage."""
    if not declaration.declared:
        return undeclared(BOUNDARY.name)
    definitions = by_symbol(model)
    types = _types_by_name(model)
    fields = frozenset(
        (m.path, m.owner, m.name) for m in model.members if m.kind is MemberKind.FIELD
    )
    findings: list[Finding] = []
    for write in model.writes:
        owner = written_type(write, definitions, types, fields)
        if owner is None:
            continue
        if owner.unit.path == write.path and is_within(write.within, owner.unit.symbol):
            continue
        unit = model.unit_at(write.path, write.line)
        if unit is None:
            continue
        findings.append(
            Finding(
                BOUNDARY,
                unit,
                layer_of(write.path, write.line, declaration, model.regions),
                f"{owner.unit.symbol}.{write.field} written by {write.within}; "
                f"owned by {owner.unit.symbol} in {owner.unit.path}",
                Evidence(write.path, write.line, f"{write.target}.{write.field}"),
            )
        )
    judged = (Coverage(BOUNDARY_JUDGED, check=BOUNDARY.name),) if findings else ()
    return CheckOutcome(tuple(findings), judged)
