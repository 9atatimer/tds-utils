"""domain/checks/composable.py -- a use case can be called with nothing in front.

Values in and out, No nesting and Helpers take values (DESIGN.ARCH-
ADHERENCE.md, The Qualities table: Composable), each a pure function over
the CodeModel.
"""

from __future__ import annotations

from adherence.domain.checks.hexagonal import names_vendor
from adherence.domain.checks.outcome import CheckOutcome, undeclared
from adherence.domain.checks.roles import (
    adapter_names,
    annotation_names,
    by_symbol,
    enclosing_function,
    is_use_case,
    named_in,
    port_names,
    short_name,
)
from adherence.domain.declaration import Declaration
from adherence.domain.finding import Evidence, Finding
from adherence.domain.model import CodeModel, Layer, UnitKind
from adherence.domain.parameters import Parameters, Vocabulary
from adherence.domain.qualities import catalog_check
from adherence.domain.records import DesignRecords, RecordsUnavailable

# --- Constants ---------------------------------------------------------------

NO_NESTING = catalog_check("No nesting")
HELPERS_TAKE_VALUES = catalog_check("Helpers take values")
VALUES_IN_AND_OUT = catalog_check("Values in and out")
RETURN = "return"

# --- Predicates --------------------------------------------------------------


def carries_mechanism(
    annotation: str | None, adapters: frozenset[str], vocabulary: Vocabulary
) -> bool:
    """Whether an annotation carries a wire format, an SDK type or a
    concrete adapter."""
    return any(
        short_name(name) in vocabulary.wire_formats
        or short_name(name) in adapters
        or ("." in name and names_vendor(name, vocabulary))
        for name in annotation_names(annotation)
    )


# --- Pure helpers ------------------------------------------------------------


def no_nesting(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
) -> CheckOutcome:
    """No function defined inside another, in a non-test unit. A test's
    layer comes from the declaration, so the check needs one."""
    if not declaration.declared:
        return undeclared(NO_NESTING.name)
    definitions = by_symbol(model)
    findings: list[Finding] = []
    for inner in model.definitions:
        unit = inner.unit
        if unit.kind is not UnitKind.FUNCTION or not inner.nested:
            continue
        if unit.layer is None or unit.layer is Layer.TEST:
            continue
        outer = enclosing_function(inner, definitions)
        if outer is None:
            continue
        findings.append(
            Finding(
                NO_NESTING,
                unit,
                unit.layer,
                f"{unit.symbol} inside {outer.unit.symbol}",
                Evidence(unit.path, unit.start, unit.symbol or ""),
            )
        )
    return CheckOutcome(tuple(findings))


def helpers_take_values(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
) -> CheckOutcome:
    """No pure helper -- a function in the domain -- takes a port or a
    callable."""
    if not declaration.declared:
        return undeclared(HELPERS_TAKE_VALUES.name)
    taken = port_names(model) | parameters.vocabulary.callables
    findings: list[Finding] = []
    for helper in model.definitions:
        unit = helper.unit
        if unit.layer is not Layer.DOMAIN or helper.signature is None:
            continue
        for parameter in helper.signature.parameters:
            if named_in(parameter, taken) is None:
                continue
            findings.append(
                Finding(
                    HELPERS_TAKE_VALUES,
                    unit,
                    unit.layer,
                    f"{parameter.name}: {parameter.annotation}",
                    Evidence(unit.path, unit.start, unit.symbol or ""),
                )
            )
    return CheckOutcome(tuple(findings))


def values_in_and_out(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
) -> CheckOutcome:
    """No use-case signature carries a wire format, an SDK type or an
    adapter handle, in a parameter or its return."""
    if not declaration.declared:
        return undeclared(VALUES_IN_AND_OUT.name)
    vocabulary = parameters.vocabulary
    adapters = adapter_names(model, vocabulary)
    findings: list[Finding] = []
    for use_case in model.definitions:
        signature = use_case.signature
        if signature is None or not is_use_case(use_case):
            continue
        carried = [
            *((p.name, p.annotation) for p in signature.parameters),
            (RETURN, signature.returns),
        ]
        unit = use_case.unit
        findings.extend(
            Finding(
                VALUES_IN_AND_OUT,
                unit,
                unit.layer,
                f"{name}: {annotation}",
                Evidence(unit.path, unit.start, unit.symbol or ""),
            )
            for name, annotation in carried
            if carries_mechanism(annotation, adapters, vocabulary)
        )
    return CheckOutcome(tuple(findings))
