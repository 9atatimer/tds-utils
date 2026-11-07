"""domain/checks/hexagonal.py -- the core depends on no mechanism.

Grep, Swap and Change (DESIGN.ARCH-ADHERENCE.md, The Qualities
table: Hexagonal), each a pure function over the CodeModel.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from adherence.domain.checks.outcome import CheckOutcome, undeclared
from adherence.domain.coverage import Coverage
from adherence.domain.declaration import Declaration, layer_of
from adherence.domain.finding import Evidence, Finding
from adherence.domain.model import (
    AccessKind,
    CodeModel,
    Definition,
    Layer,
    ReferenceKind,
    Unit,
    UnitKind,
)
from adherence.domain.parameters import Parameters, Vocabulary
from adherence.domain.qualities import catalog_check
from adherence.domain.records import DesignRecords, RecordsUnavailable, Seam
from adherence.domain.source import source_lines

# --- Constants ---------------------------------------------------------------

GREP = catalog_check("Grep")
SWAP = catalog_check("Swap")
CHANGE = catalog_check("Change")
# Where a seam's port, policy or parameter may live: anywhere but an
# adapter or a test.
SEAM_LAYERS = frozenset(
    {Layer.DOMAIN, Layer.PORTS, Layer.APPLICATION, Layer.COMPOSITION_ROOT}
)
CORE = frozenset({Layer.DOMAIN, Layer.APPLICATION})
# A type declaring an interface by its base (the last dotted part, any
# subscript dropped), and a method declared abstract by its decorator: a
# port whose methods are only docstrings carries no stub marker.
INTERFACE_BASES = frozenset({"Protocol"})
ABSTRACT_DECORATORS = frozenset({"abstractmethod"})
# The suffix a port's name may carry that its fake's name drops
# (CodeModelPort, FakeCodeModel).
PORT_SUFFIX = "Port"
# Special methods that build, describe or compare an object rather than
# define what a port offers: a fake need not share them. Every other
# special method (__call__, __enter__, __iter__) is part of an interface.
NON_INTERFACE_METHODS = frozenset(
    {
        "__init__",
        "__new__",
        "__post_init__",
        "__init_subclass__",
        "__class_getitem__",
        "__subclasshook__",
        "__repr__",
        "__str__",
        "__eq__",
        "__hash__",
    }
)


@dataclass(frozen=True, slots=True)
class _Hit:
    """A mechanism named at one line: what is named and the text naming it."""

    path: str
    line: int
    subject: str
    text: str


# --- Predicates --------------------------------------------------------------


def names_vendor(module: str, vocabulary: Vocabulary) -> bool:
    """Whether a module, or a dotted prefix of it, is a vendor, an SDK, the
    filesystem or the network."""
    parts = module.split(".")
    return any(
        ".".join(parts[:end]) in vocabulary.vendors for end in range(1, len(parts) + 1)
    )


def is_model_id(text: str, vocabulary: Vocabulary) -> bool:
    """Whether a string literal names a model."""
    lowered = text.lower()
    return any(lowered.startswith(prefix) for prefix in vocabulary.model_ids)


# --- Pure helpers ------------------------------------------------------------


def bounded(text: str, bound: int) -> str:
    """The first line of a text, stripped and cut at the evidence bound: what
    a finding may name of source text (a string literal may span lines)."""
    return next(iter(source_lines(text)), "").strip()[:bound]


def _mechanisms(model: CodeModel, vocabulary: Vocabulary) -> list[_Hit]:
    """Every vendor import, environment read, filesystem or module-loader
    call, and model id in the model. An
    import naming a vendor is one whatever it resolves to: an in-repo copy
    of the vendor's package does not make it the repository's own."""
    return [
        *(
            _Hit(e.path, e.line, e.imported, e.text)
            for e in model.imports
            if names_vendor(e.imported, vocabulary)
        ),
        *(
            _Hit(a.path, a.line, a.target, a.target)
            for a in model.accesses
            if a.kind is AccessKind.ENVIRONMENT
        ),
        *(
            _Hit(c.path, c.line, c.callee, c.callee)
            for c in model.calls
            if c.callee in vocabulary.mechanism_calls
        ),
        *(
            _Hit(r.path, r.line, r.text, r.text)
            for r in model.references
            if r.kind is ReferenceKind.STRING and is_model_id(r.text, vocabulary)
        ),
    ]


def grep(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
) -> CheckOutcome:
    """No domain or application unit names a vendor, an SDK, the
    environment, the filesystem, the network, or a model id."""
    if not declaration.declared:
        return undeclared(GREP.name)
    findings: list[Finding] = []
    bound = parameters.limits.evidence_bound
    for hit in _mechanisms(model, parameters.vocabulary):
        layer = layer_of(hit.path, hit.line, declaration, model.regions)
        unit = model.unit_at(hit.path, hit.line)
        if layer in CORE and unit is not None:
            findings.append(
                Finding(
                    GREP,
                    unit,
                    layer,
                    bounded(hit.subject, bound),
                    Evidence(hit.path, hit.line, hit.text),
                )
            )
    return CheckOutcome(tuple(findings))


def _name(definition: Definition) -> str:
    return (definition.unit.symbol or "").rpartition(".")[2]


def _methods(model: CodeModel) -> dict[tuple[str, str], list[Definition]]:
    """Each type's methods, keyed by the type's path and symbol."""
    methods: dict[tuple[str, str], list[Definition]] = {}
    for d in model.definitions:
        if d.unit.kind is UnitKind.FUNCTION and d.parent is not None:
            methods.setdefault((d.unit.path, d.parent), []).append(d)
    return methods


def _types(model: CodeModel) -> list[Definition]:
    return [d for d in model.definitions if d.unit.kind is UnitKind.TYPE]


def _last_part(written: str) -> str:
    """A base or decorator as written, without its subscript or call and
    its dotted prefix."""
    return written.partition("[")[0].partition("(")[0].rpartition(".")[2].strip()


def is_port(definition: Definition, methods: Sequence[Definition]) -> bool:
    """Whether a type is a port: in the ports layer, declaring methods, and
    either an interface by its base (a Protocol), declaring an abstract
    method, or implementing none of its methods."""
    if definition.unit.layer is not Layer.PORTS or not methods:
        return False
    return (
        any(_last_part(b) in INTERFACE_BASES for b in definition.bases)
        or any(
            _last_part(d) in ABSTRACT_DECORATORS for m in methods for d in m.decorators
        )
        or all(m.body.stub_markers for m in methods)
    )


def _method_names(methods: Sequence[Definition]) -> set[str]:
    """The methods that make an interface: named ones and the special
    methods a caller uses the object through; never a name-mangled one."""
    return {_name(m) for m in methods if _interface_method(_name(m))}


def _interface_method(name: str) -> bool:
    if not name.startswith("__"):
        return True
    return name.endswith("__") and name not in NON_INTERFACE_METHODS


def implements(
    candidate: Definition,
    candidate_methods: Sequence[Definition],
    port: Definition,
    port_methods: Sequence[Definition],
) -> bool:
    """Whether a type implements a port: it names the port as a base, or its
    name ends with the port's (less any Port suffix) and it has every method
    the port declares. Shared method names alone do not make a fake of one
    port a fake of another."""
    if candidate is port:
        return False
    if any(base.rpartition(".")[2] == _name(port) for base in candidate.bases):
        return True
    stem = _name(port).removesuffix(PORT_SUFFIX) or _name(port)
    wanted = _method_names(port_methods)
    return (
        _name(candidate).endswith(stem)
        and bool(wanted)
        and wanted <= _method_names(candidate_methods)
    )


def is_fake(definition: Definition, vocabulary: Vocabulary) -> bool:
    """Whether an implementation is a fake: a test unit, or a type whose name
    carries one of the vocabulary's fake prefixes."""
    return definition.unit.layer is Layer.TEST or any(
        _name(definition).startswith(prefix) for prefix in vocabulary.fakes
    )


def swap(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
) -> CheckOutcome:
    """Every port has at least one fake, anywhere in the repository."""
    if not declaration.declared:
        return undeclared(SWAP.name)
    methods = _methods(model)
    types = _types(model)
    findings: list[Finding] = []
    for port in types:
        own = methods.get((port.unit.path, port.unit.symbol or ""), [])
        if not is_port(port, own):
            continue
        faked = any(
            is_fake(t, parameters.vocabulary)
            and implements(
                t, methods.get((t.unit.path, t.unit.symbol or ""), []), port, own
            )
            for t in types
        )
        if not faked:
            unit = port.unit
            findings.append(
                Finding(
                    SWAP,
                    unit,
                    unit.layer,
                    _name(port),
                    Evidence(unit.path, unit.start, _name(port)),
                )
            )
    return CheckOutcome(tuple(findings))


def _seam_finding(seam: Seam, subject: str) -> Finding:
    unit = Unit(seam.path, UnitKind.SEAM, seam.name, seam.line, seam.line, None)
    return Finding(
        CHANGE, unit, None, subject, Evidence(seam.path, seam.line, seam.name)
    )


def change(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
) -> CheckOutcome:
    """Every seam the architecture record names exists as exactly one port,
    policy or parameter: one type of that name outside the adapters and the
    tests."""
    if not declaration.declared:
        return undeclared(CHANGE.name)
    if isinstance(records, RecordsUnavailable):
        return CheckOutcome(
            coverage=(Coverage(records.reason, check="Change"),), ran=False
        )
    homes: dict[str, list[str]] = {}
    for t in _types(model):
        if t.unit.layer in SEAM_LAYERS:
            homes.setdefault(_name(t), []).append(t.unit.path)
    findings: list[Finding] = []
    for seam in records.seams:
        found = homes.get(seam.name, [])
        if not found:
            findings.append(_seam_finding(seam, f"{seam.name}: no {seam.kind.value}"))
        elif len(found) > 1:
            where = ", ".join(sorted(found))
            findings.append(_seam_finding(seam, f"{seam.name}: defined in {where}"))
    return CheckOutcome(tuple(findings))
