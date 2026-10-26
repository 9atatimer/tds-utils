"""domain/checks/ddd.py -- each concept named once, with one owner.

The rule parts of Language, Boundary and Anemic (DESIGN.ARCH-ADHERENCE.md,
The Qualities table: Domain-driven), each a pure function over the
CodeModel. Their judged parts -- same_concept, invariant_broken,
rules_elsewhere -- and the Decision question are asked by no judge in this
suite version; what they would be asked about is coverage.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from adherence.domain.checks.outcome import CheckOutcome, undeclared
from adherence.domain.checks.roles import (
    annotation_names,
    by_symbol,
    is_within,
    port_names,
    short_name,
    use_cases,
)
from adherence.domain.coverage import Coverage
from adherence.domain.declaration import Declaration, layer_of
from adherence.domain.finding import Evidence, Finding
from adherence.domain.model import (
    CodeModel,
    Definition,
    Layer,
    MemberKind,
    UnitKind,
    Write,
)
from adherence.domain.parameters import Parameters, Vocabulary
from adherence.domain.qualities import catalog_check
from adherence.domain.records import DesignRecords, RecordsUnavailable, Term

# --- Constants ---------------------------------------------------------------

BOUNDARY = catalog_check("Boundary")
LANGUAGE = catalog_check("Language")
ANEMIC = catalog_check("Anemic")
# A method that only sets a type's fields up is no behavior of its own.
INITIALISER = "__init__"
# The bases that make a type an enumeration: a closed set of names, whose
# members are no fields awaiting rules.
ENUM_BASES = frozenset({"Enum", "IntEnum", "StrEnum", "Flag", "IntFlag"})
# One word of an identifier or a term: an acronym, a capitalised or
# lower-case word, or a number (`SARIFReport` -> SARIF, Report).
WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+")
PLURAL = "s"
# A port's role suffix: `RepositoryPort` is the term Repository's port.
PORT_SUFFIX = "port"
# The layers whose types are the mechanism, not the problem: a port, an
# adapter or the composition root's wiring is no noun of the domain.
MECHANISM_LAYERS = frozenset({Layer.PORTS, Layer.ADAPTERS, Layer.COMPOSITION_ROOT})
NO_JUDGE = "no judged question is asked in this suite version"
BOUNDARY_JUDGED = (
    f"the judged part (invariant_broken: does the foreign write break an "
    f"invariant?) {NO_JUDGE}"
)
LANGUAGE_JUDGED = (
    f"the judged part (same_concept: are two differently spelled nouns one "
    f"concept?) {NO_JUDGE}"
)

ANEMIC_JUDGED = (
    f"all fields and no behavior; whether its rules live in another unit "
    f"(rules_elsewhere) is the judged part, and {NO_JUDGE}"
)

# --- Predicates --------------------------------------------------------------


def _spelled_alike(term: Sequence[str], noun: Sequence[str]) -> bool:
    """The same words, or the same with the last one plural in either."""
    if tuple(term) == tuple(noun):
        return True
    return (
        len(term) == len(noun) > 0
        and tuple(term[:-1]) == tuple(noun[:-1])
        and PLURAL in (noun[-1].removeprefix(term[-1]), term[-1].removeprefix(noun[-1]))
    )


def defines(term: Sequence[str], noun: Sequence[str]) -> bool:
    """Whether a term's words define a noun's: the same words, or the same
    with the last one plural in the term or the noun, with or without a
    port's role suffix on the noun (`RepositoryPort` for Repository)."""
    if _spelled_alike(term, noun):
        return True
    return len(noun) > 1 and noun[-1] == PORT_SUFFIX and _spelled_alike(term, noun[:-1])


def is_enum(definition: Definition) -> bool:
    """Whether a type is an enumeration, by a base it names."""
    return any(short_name(base) in ENUM_BASES for base in definition.bases)


# --- Pure helpers ------------------------------------------------------------


def words(text: str) -> tuple[str, ...]:
    """An identifier's or a term's words, lower-cased: CamelCase, snake_case
    and spaced spellings of one name give the same words."""
    return tuple(w.lower() for w in WORD.findall(text))


def mechanism_names(model: CodeModel) -> frozenset[str]:
    """The names that are no noun of the problem: every port, and every type
    the ports, adapters and composition-root layers define."""
    return port_names(model) | frozenset(
        short_name(d.unit.symbol)
        for d in model.definitions
        if d.unit.kind is UnitKind.TYPE and d.unit.layer in MECHANISM_LAYERS
    )


def signature_nouns(
    use_case: Definition, vocabulary: Vocabulary, mechanism: frozenset[str]
) -> list[str]:
    """The type names a use case's signature carries, each once, in order,
    without the language's own types and without the mechanism's."""
    signature = use_case.signature
    if signature is None:
        return []
    annotations = [*(p.annotation for p in signature.parameters), signature.returns]
    nouns: list[str] = []
    for annotation in annotations:
        for name in annotation_names(annotation):
            noun = short_name(name)
            if (
                noun not in vocabulary.plain_types
                and noun not in mechanism
                and noun not in nouns
            ):
                nouns.append(noun)
    return nouns


def _defined(noun: str, terms: Sequence[Term]) -> bool:
    return any(defines(words(t.name), words(noun)) for t in terms)


def language(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
) -> CheckOutcome:
    """Every noun in a use-case signature -- every type name it carries but
    a port's or another mechanism type's -- is defined in the design's
    Domain Language under that spelling. The judged part is coverage."""
    if not declaration.declared:
        return undeclared(LANGUAGE.name)
    if isinstance(records, RecordsUnavailable):
        return CheckOutcome(
            coverage=(Coverage(records.reason, check=LANGUAGE.name),), ran=False
        )
    mechanism = mechanism_names(model)
    findings: list[Finding] = []
    for use_case in use_cases(model):
        unit = use_case.unit
        findings.extend(
            Finding(
                LANGUAGE,
                unit,
                unit.layer,
                f"{noun} in {unit.symbol}",
                Evidence(unit.path, unit.start, unit.symbol or ""),
            )
            for noun in signature_nouns(use_case, parameters.vocabulary, mechanism)
            if not _defined(noun, records.domain_language)
        )
    return CheckOutcome(
        tuple(findings), (Coverage(LANGUAGE_JUDGED, check=LANGUAGE.name),)
    )


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


def anemic(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
) -> CheckOutcome:
    """The rule part finds each domain type that is all fields and no
    behavior -- fields, and no method but an initialiser -- and is no
    enumeration. Whether such a
    type is anemic, its rules living in another unit, is the judged part's
    question, so the rule part finds nothing by itself: each type it finds
    is coverage until a judge answers."""
    if not declaration.declared:
        return undeclared(ANEMIC.name)
    fields: set[tuple[str, str]] = set()
    behaving: set[tuple[str, str]] = set()
    for m in model.members:
        if m.kind is MemberKind.FIELD:
            fields.add((m.path, m.owner))
        elif m.name != INITIALISER:
            behaving.add((m.path, m.owner))
    asked = [
        Coverage(
            f"{d.unit.symbol}: {ANEMIC_JUDGED}", check=ANEMIC.name, path=d.unit.path
        )
        for d in model.definitions
        if d.unit.kind is UnitKind.TYPE
        and d.unit.layer is Layer.DOMAIN
        and not is_enum(d)
        and (key := (d.unit.path, d.unit.symbol or "")) in fields
        and key not in behaving
    ]
    return CheckOutcome(coverage=tuple(asked))
