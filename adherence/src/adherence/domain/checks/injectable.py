"""domain/checks/injectable.py -- dependencies arrive at the flow function.

Ports as keywords, No self-wiring and No reach (DESIGN.ARCH-ADHERENCE.md,
The Qualities table: Injectable), each a pure function over the
CodeModel.
"""

from __future__ import annotations

from collections.abc import Sequence

from adherence.domain.checks.hexagonal import CORE
from adherence.domain.checks.outcome import CheckOutcome, undeclared
from adherence.domain.checks.roles import (
    adapter_names,
    is_use_case,
    is_within,
    named_in,
    port_names,
    short_name,
)
from adherence.domain.declaration import Declaration, layer_of
from adherence.domain.finding import Evidence, Finding
from adherence.domain.model import AccessKind, CodeModel, Parameter, ReferenceKind
from adherence.domain.parameters import Parameters, Vocabulary
from adherence.domain.qualities import catalog_check
from adherence.domain.records import DesignRecords, RecordsUnavailable

# --- Constants ---------------------------------------------------------------

PORTS_AS_KEYWORDS = catalog_check("Ports as keywords")
NO_SELF_WIRING = catalog_check("No self-wiring")
NO_REACH = catalog_check("No reach")
REACHED = {
    AccessKind.ENVIRONMENT: "the environment",
    AccessKind.GLOBAL: "a global",
}
SINGLETON = "a singleton"

# --- Predicates --------------------------------------------------------------


def is_singleton(name: str, vocabulary: Vocabulary) -> bool:
    """Whether a name chain is, or runs through, a singleton."""
    return any(name == s or name.startswith(f"{s}.") for s in vocabulary.singletons)


# --- Pure helpers ------------------------------------------------------------


def misplaced_ports(
    parameters: Sequence[Parameter], ports: frozenset[str]
) -> list[Parameter]:
    """The ports among a use case's parameters that are taken by position,
    or that come before every value the use case takes."""
    is_port = [named_in(p, ports) is not None for p in parameters]
    return [
        p
        for index, p in enumerate(parameters)
        if is_port[index]
        and (not p.keyword_only or (all(is_port[:index]) and not all(is_port[index:])))
    ]


def ports_as_keywords(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
) -> CheckOutcome:
    """Every port a use case takes is a named dependency after its values:
    a keyword-only parameter, never taken by position, and never before
    every value. A method's own first parameter is no value."""
    if not declaration.declared:
        return undeclared(PORTS_AS_KEYWORDS.name)
    ports = port_names(model)
    findings: list[Finding] = []
    for use_case in model.definitions:
        signature = use_case.signature
        if signature is None or not is_use_case(use_case):
            continue
        unit = use_case.unit
        taken = signature.parameters[1 if use_case.parent is not None else 0 :]
        findings.extend(
            Finding(
                PORTS_AS_KEYWORDS,
                unit,
                unit.layer,
                f"{p.name}: {p.annotation}",
                Evidence(unit.path, unit.start, unit.symbol or ""),
            )
            for p in misplaced_ports(taken, ports)
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
    adapters = adapter_names(model)
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


def _reaches(model: CodeModel, vocabulary: Vocabulary) -> list[tuple[str, int, str]]:
    """Every read of the environment, a global or a singleton: its path,
    its line and what it reached."""
    return [
        *((a.path, a.line, f"{REACHED[a.kind]}: {a.target}") for a in model.accesses),
        *(
            (r.path, r.line, f"{SINGLETON}: {r.text}")
            for r in model.references
            if r.kind is ReferenceKind.NAME and is_singleton(r.text, vocabulary)
        ),
    ]


def no_reach(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
) -> CheckOutcome:
    """No use case or domain unit -- nothing in the application or domain
    layer -- reads a global, a singleton or the environment."""
    if not declaration.declared:
        return undeclared(NO_REACH.name)
    findings: list[Finding] = []
    for path, line, reached in _reaches(model, parameters.vocabulary):
        layer = layer_of(path, line, declaration, model.regions)
        unit = model.unit_at(path, line)
        if layer in CORE and unit is not None:
            findings.append(
                Finding(NO_REACH, unit, layer, reached, Evidence(path, line, reached))
            )
    return CheckOutcome(tuple(findings))
