"""domain/checks/composable.py -- a use case can be called with nothing in front.

Values in and out, No nesting and Helpers take values (DESIGN.ARCH-
ADHERENCE.md, The Qualities table: Composable), each a pure function over
the CodeModel.
"""

from __future__ import annotations

from adherence.domain.checks.outcome import CheckOutcome, undeclared
from adherence.domain.checks.roles import (
    by_symbol,
    enclosing_function,
    named_in,
    port_names,
)
from adherence.domain.declaration import Declaration
from adherence.domain.finding import Evidence, Finding
from adherence.domain.model import CodeModel, Layer, UnitKind
from adherence.domain.parameters import Parameters
from adherence.domain.qualities import catalog_check
from adherence.domain.records import DesignRecords, RecordsUnavailable

# --- Constants ---------------------------------------------------------------

NO_NESTING = catalog_check("No nesting")
HELPERS_TAKE_VALUES = catalog_check("Helpers take values")

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
