"""domain/checks/injectable.py -- dependencies arrive at the flow function.

Ports as keywords, No self-wiring and No reach (DESIGN.ARCH-ADHERENCE.md,
The Qualities table: Injectable), each a pure function over the
CodeModel.
"""

from __future__ import annotations

from adherence.domain.checks.outcome import CheckOutcome, undeclared
from adherence.domain.checks.roles import (
    adapter_names,
    is_use_case,
    is_within,
    named_in,
    port_names,
    short_name,
)
from adherence.domain.declaration import Declaration
from adherence.domain.finding import Evidence, Finding
from adherence.domain.model import CodeModel
from adherence.domain.parameters import Parameters
from adherence.domain.qualities import catalog_check
from adherence.domain.records import DesignRecords, RecordsUnavailable

# --- Constants ---------------------------------------------------------------

PORTS_AS_KEYWORDS = catalog_check("Ports as keywords")
NO_SELF_WIRING = catalog_check("No self-wiring")

# --- Pure helpers ------------------------------------------------------------


def ports_as_keywords(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
) -> CheckOutcome:
    """Every port a use case takes is a named dependency after its values:
    a keyword-only parameter, so it is never taken by position."""
    if not declaration.declared:
        return undeclared(PORTS_AS_KEYWORDS.name)
    ports = port_names(model)
    findings: list[Finding] = []
    for use_case in model.definitions:
        signature = use_case.signature
        if signature is None or not is_use_case(use_case):
            continue
        unit = use_case.unit
        findings.extend(
            Finding(
                PORTS_AS_KEYWORDS,
                unit,
                unit.layer,
                f"{p.name}: {p.annotation}",
                Evidence(unit.path, unit.start, unit.symbol or ""),
            )
            for p in signature.parameters
            if not p.keyword_only and named_in(p, ports) is not None
        )
    return CheckOutcome(tuple(findings))


def no_self_wiring(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
) -> CheckOutcome:
    """No use case constructs a concrete adapter: no call in it, or in a
    function nested in it, names a concrete adapter the model defines."""
    if not declaration.declared:
        return undeclared(NO_SELF_WIRING.name)
    adapters = adapter_names(model, parameters.vocabulary)
    findings: list[Finding] = []
    for use_case in model.definitions:
        if not is_use_case(use_case):
            continue
        unit = use_case.unit
        findings.extend(
            Finding(
                NO_SELF_WIRING,
                unit,
                unit.layer,
                call.callee,
                Evidence(call.path, call.line, call.callee),
            )
            for call in model.calls
            if call.path == unit.path
            and is_within(call.within, unit.symbol)
            and short_name(call.callee) in adapters
        )
    return CheckOutcome(tuple(findings))
