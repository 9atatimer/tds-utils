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
    INITIALISERS,
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
    Conditional,
    Definition,
    Layer,
    MemberKind,
    ReferenceKind,
    Unit,
    UnitKind,
    Write,
    code_language_of,
)
from adherence.domain.parameters import Parameters, Vocabulary
from adherence.domain.qualities import catalog_check
from adherence.domain.questions import (
    INVARIANT_BROKEN,
    RULES_ELSEWHERE,
    SAME_CONCEPT,
    SCATTERED_POLICY,
    Ask,
    definition_text,
)
from adherence.domain.records import DesignRecords, RecordsUnavailable, Term

# --- Constants ---------------------------------------------------------------

BOUNDARY = catalog_check("Boundary")
LANGUAGE = catalog_check("Language")
ANEMIC = catalog_check("Anemic")


DECISION = catalog_check("Decision")
# An attribute is a discriminant two units can share; a bare name is a
# local of each unit, never the same thing twice.
ATTRIBUTE = "."
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
NO_TYPE = "no type of that name is defined in the code"


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
    without its language's own types and without the mechanism's."""
    signature = use_case.signature
    if signature is None:
        return []
    code_language = code_language_of(use_case.unit.path)
    annotations = [*(p.annotation for p in signature.parameters), signature.returns]
    nouns: list[str] = []
    for annotation in annotations:
        for name in annotation_names(annotation):
            noun = short_name(name)
            if (
                not vocabulary.is_plain(noun, code_language)
                and noun not in mechanism
                and noun not in nouns
            ):
                nouns.append(noun)
    return nouns


def _defined(noun: str, terms: Sequence[Term]) -> bool:
    return any(defines(words(t.name), words(noun)) for t in terms)


def _term_of(noun: str, terms: Sequence[Term]) -> Term | None:
    """The Domain Language term that defines a noun, if one does."""
    return next((t for t in terms if defines(words(t.name), words(noun))), None)


def shares_a_word(first: str, second: str) -> bool:
    """Whether two nouns have a word in common, a plural matching its
    singular (`OrderRecord` and `Orders`)."""
    return any(_spelled_alike((a,), (b,)) for a in words(first) for b in words(second))


def _signature_sites(
    model: CodeModel, vocabulary: Vocabulary, mechanism: frozenset[str]
) -> dict[str, list[Definition]]:
    """Every noun a use-case signature carries, with the use cases carrying it."""
    sites: dict[str, list[Definition]] = {}
    for use_case in use_cases(model):
        for noun in signature_nouns(use_case, vocabulary, mechanism):
            sites.setdefault(noun, []).append(use_case)
    return sites


def _domain_types(model: CodeModel) -> dict[str, Definition]:
    """The domain layer's types, by name, the first of each name."""
    types: dict[str, Definition] = {}
    for d in model.definitions:
        if d.unit.kind is UnitKind.TYPE and d.unit.layer is Layer.DOMAIN:
            types.setdefault(short_name(d.unit.symbol), d)
    return types


def _described(
    noun: str,
    types: Mapping[str, Definition],
    sites: Mapping[str, Sequence[Definition]],
) -> str:
    """One noun as the judge reads it: its definition and where it is used."""
    definition = types.get(noun)
    used = ", ".join(d.unit.symbol or "" for d in sites.get(noun, ())) or "none"
    shown = definition_text(definition) if definition is not None else NO_TYPE
    return f"{noun}:\n{shown}\nused in the use-case signatures of: {used}"


def _same_concept_ask(
    pair: tuple[str, str],
    term: Term,
    types: Mapping[str, Definition],
    sites: Mapping[str, Sequence[Definition]],
) -> Ask:
    undefined, defined = pair
    definition = types.get(undefined) or sites[undefined][0]
    unit = definition.unit
    return Ask(
        check=LANGUAGE,
        question=SAME_CONCEPT,
        unit=unit,
        layer=unit.layer,
        subject=f"{undefined} and {defined}: one concept under two spellings",
        evidence=Evidence(unit.path, unit.start, undefined),
        text=definition_text(definition),
        context=(
            f"{_described(undefined, types, sites)}\n\n"
            f"{_described(defined, types, sites)}\n"
            f"the Domain Language defines {defined} as the term {term.name}"
        ),
    )


def same_concept_asks(
    model: CodeModel, records: DesignRecords, vocabulary: Vocabulary
) -> list[Ask]:
    """Language's judged part: each noun the Domain Language does not define
    -- a domain type, or a noun a use-case signature carries -- paired with
    each term's noun in the code that shares a word with it, asked whether
    the two are one concept. Two nouns sharing no word are not asked about."""
    sites = _signature_sites(model, vocabulary, mechanism_names(model))
    types = _domain_types(model)
    nouns = list(dict.fromkeys([*types, *sites]))
    terms: dict[str, tuple[str, Term]] = {}
    for noun in nouns:
        term = _term_of(noun, records.domain_language)
        if term is not None:
            terms.setdefault(term.name, (noun, term))
    return [
        _same_concept_ask((noun, defined), term, types, sites)
        for noun in nouns
        if _term_of(noun, records.domain_language) is None
        for defined, term in terms.values()
        if shares_a_word(noun, defined)
    ]


def language(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
) -> CheckOutcome:
    """Every noun in a use-case signature -- every type name it carries but
    a port's or another mechanism type's -- is defined in the design's
    Domain Language under that spelling. The judged part asks whether an
    undefined noun is a defined one's other spelling."""
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
        tuple(findings),
        questions=tuple(same_concept_asks(model, records, parameters.vocabulary)),
    )


def _types_by_name(model: CodeModel) -> dict[str, list[Definition]]:
    """Every type the model defines, by its name."""
    types: dict[str, list[Definition]] = {}
    for d in model.definitions:
        if d.unit.kind is UnitKind.TYPE:
            types.setdefault(short_name(d.unit.symbol), []).append(d)
    return types


def local_source(write: Write, local: Mapping[tuple[str, str | None, str], str]) -> str:
    """The name a write's object stands for in its writer: the object
    itself, or what a local binding in the writer binds it to, through
    every alias of an alias."""
    name = write.target
    seen: set[str] = set()
    while (bound := local.get((write.path, write.within, name))) is not None:
        if name in seen:
            break
        seen.add(name)
        name = bound
    return name


def written_type(
    write: Write,
    definitions: Mapping[tuple[str, str], Definition],
    types: Mapping[str, list[Definition]],
    fields: frozenset[tuple[str, str, str]],
    local: Mapping[tuple[str, str | None, str], str],
) -> Definition | None:
    """The type whose declared field a write assigns, when the object
    written is a parameter of the writer annotated with that type, or a
    local name bound to one; None when the write cannot be pinned on a
    type."""
    writer = definitions.get((write.path, write.within or ""))
    if writer is None or writer.signature is None:
        return None
    source = local_source(write, local)
    parameter = next((p for p in writer.signature.parameters if p.name == source), None)
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


def _invariant_ask(
    write: Write,
    owner: Definition,
    writer: Definition | None,
    unit: Unit,
    layer: Layer | None,
    evidence: Evidence,
) -> Ask:
    """Boundary's judged part about one foreign write: the writer as the
    unit's text, the owning type and the write as the data."""
    owned = owner.unit.symbol
    return Ask(
        check=BOUNDARY,
        question=INVARIANT_BROKEN,
        unit=unit,
        layer=layer,
        subject=(
            f"{owned}.{write.field} written by {write.within}: can break an "
            f"invariant of {owned}"
        ),
        evidence=evidence,
        text=definition_text(writer) if writer is not None else "",
        context=(
            f"the owning type, {owned} in {owner.unit.path}:\n"
            f"{definition_text(owner)}\n\n"
            f"the write: {write.target}.{write.field} at "
            f"{write.path}:{write.line} in {write.within}"
        ),
    )


def boundary(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
) -> CheckOutcome:
    """No value type has a field written outside its owning unit, the type
    itself. The rule part reads a write whose object is a parameter of the
    writer annotated with the type, or a local name bound to one; the
    judged part asks whether each such write can break an invariant."""
    if not declaration.declared:
        return undeclared(BOUNDARY.name)
    definitions = by_symbol(model)
    types = _types_by_name(model)
    fields = frozenset(
        (m.path, m.owner, m.name) for m in model.members if m.kind is MemberKind.FIELD
    )
    local: dict[tuple[str, str | None, str], str] = {
        (b.path, b.within, b.name): b.value
        for b in model.bindings
        if b.within is not None
    }
    findings: list[Finding] = []
    asks: list[Ask] = []
    for write in model.writes:
        owner = written_type(write, definitions, types, fields, local)
        if owner is None:
            continue
        if owner.unit.path == write.path and is_within(write.within, owner.unit.symbol):
            continue
        unit = model.unit_at(write.path, write.line)
        if unit is None:
            continue
        layer = layer_of(write.path, write.line, declaration, model.regions)
        evidence = Evidence(write.path, write.line, f"{write.target}.{write.field}")
        findings.append(
            Finding(
                BOUNDARY,
                unit,
                layer,
                f"{owner.unit.symbol}.{write.field} written by {write.within}; "
                f"owned by {owner.unit.symbol} in {owner.unit.path}",
                evidence,
            )
        )
        writer = definitions.get((write.path, write.within or ""))
        asked = writer.unit if writer is not None else unit
        asks.append(_invariant_ask(write, owner, writer, asked, layer, evidence))
    return CheckOutcome(tuple(findings), questions=tuple(asks))


def computes_over(
    function: Definition, owner: str, fields: frozenset[str], reads: frozenset[str]
) -> bool:
    """Whether a function reads one of a type's fields through a parameter
    annotated with the type: `reads` holds the dotted names it references."""
    if function.signature is None:
        return False
    return any(
        f"{p.name}.{name}" in reads
        for p in function.signature.parameters
        if owner in {short_name(n) for n in annotation_names(p.annotation)}
        for name in fields
    )


def _references_by_scope(model: CodeModel) -> dict[tuple[str, str], frozenset[str]]:
    """The dotted names each definition references, by its path and symbol,
    with every shorter prefix of each (`r.total.cents` reads `r.total`)."""
    found: dict[tuple[str, str], set[str]] = {}
    for r in model.references:
        if r.kind is ReferenceKind.NAME and r.within is not None:
            parts = r.text.split(".")
            found.setdefault((r.path, r.within), set()).update(
                ".".join(parts[:n]) for n in range(2, len(parts) + 1)
            )
    return {scope: frozenset(names) for scope, names in found.items()}


def _rules_elsewhere_ask(type_: Definition, computing: Sequence[Definition]) -> Ask:
    unit = type_.unit
    holders = ", ".join(d.unit.symbol or "" for d in computing)
    shown = "\n\n".join(
        f"{d.unit.path}:{d.unit.start}:\n{definition_text(d)}" for d in computing
    )
    return Ask(
        check=ANEMIC,
        question=RULES_ELSEWHERE,
        unit=unit,
        layer=unit.layer,
        subject=f"{unit.symbol}: all fields; its rules live in {holders}",
        evidence=Evidence(unit.path, unit.start, unit.symbol or ""),
        text=definition_text(type_),
        context=f"the units computing over its fields:\n\n{shown}",
    )


def anemic(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
) -> CheckOutcome:
    """The rule part finds each domain type that is all fields and no
    behavior -- fields, and no method but an initialiser -- and is no
    enumeration, and the units outside it that compute over its fields.
    Whether its rules live in those units is the judged part's question, so
    the rule part finds nothing by itself; a type nothing computes over is a
    plain value, and is not asked about."""
    if not declaration.declared:
        return undeclared(ANEMIC.name)
    fields: dict[tuple[str, str], set[str]] = {}
    behaving: set[tuple[str, str]] = set()
    for m in model.members:
        if m.kind is MemberKind.FIELD:
            fields.setdefault((m.path, m.owner), set()).add(m.name)
        elif m.name not in INITIALISERS:
            behaving.add((m.path, m.owner))
    reads = _references_by_scope(model)
    functions = [d for d in model.definitions if d.unit.kind is UnitKind.FUNCTION]
    asks: list[Ask] = []
    for d in model.definitions:
        key = (d.unit.path, d.unit.symbol or "")
        if (
            d.unit.kind is not UnitKind.TYPE
            or d.unit.layer is not Layer.DOMAIN
            or is_enum(d)
            or key not in fields
            or key in behaving
        ):
            continue
        owner = short_name(d.unit.symbol)
        computing = [
            f
            for f in functions
            if not (
                f.unit.path == d.unit.path and is_within(f.unit.symbol, d.unit.symbol)
            )
            and computes_over(
                f,
                owner,
                frozenset(fields[key]),
                reads.get((f.unit.path, f.unit.symbol or ""), frozenset()),
            )
        ]
        if computing:
            asks.append(_rules_elsewhere_ask(d, computing))
    return CheckOutcome(questions=tuple(asks))


def _branched(
    model: CodeModel, declaration: Declaration
) -> dict[str, list[tuple[Conditional, Layer]]]:
    """The conditionals of covered, non-test code that branch on an
    attribute, each with its layer, by the attribute, in model order."""
    shared: dict[str, list[tuple[Conditional, Layer]]] = {}
    for c in model.conditionals:
        layer = layer_of(c.path, c.line, declaration, model.regions)
        if layer is None or layer is Layer.TEST or ATTRIBUTE not in c.discriminant:
            continue
        shared.setdefault(c.discriminant, []).append((c, layer))
    return shared


def _holder_text(
    conditional: Conditional, definitions: Mapping[tuple[str, str], Definition]
) -> str:
    holder = definitions.get((conditional.path, conditional.within or ""))
    text = definition_text(holder) if holder is not None else ""
    return f"{conditional.path}:{conditional.line} in {conditional.within}:\n{text}"


def _scattered_policy_ask(
    discriminant: str,
    branched: Sequence[tuple[Conditional, Layer]],
    model: CodeModel,
    definitions: Mapping[tuple[str, str], Definition],
) -> Ask | None:
    """The scattered_policy question about one shared discriminant, asked of
    the unit holding its first conditional; None when no unit holds it."""
    first, layer = branched[0]
    found = definitions.get((first.path, first.within or ""))
    unit = found.unit if found is not None else model.unit_at(first.path, first.line)
    if unit is None:
        return None
    places = ", ".join(f"{c.within} ({c.path}:{c.line})" for c, _ in branched)
    shown = "\n\n".join(_holder_text(c, definitions) for c, _ in branched)
    return Ask(
        check=DECISION,
        question=SCATTERED_POLICY,
        unit=unit,
        layer=layer,
        subject=f"{discriminant}: branched on in {places}",
        evidence=Evidence(first.path, first.line, discriminant),
        text=definition_text(found) if found is not None else "",
        context=f"the shared discriminant: {discriminant}\n\n{shown}",
    )


def decision(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
) -> CheckOutcome:
    """Asks the judge, of each attribute two or more units of covered,
    non-test code branch on, whether those conditionals spread one decision
    that belongs in one named policy; it finds nothing by itself."""
    if not declaration.declared:
        return undeclared(DECISION.name)
    definitions = by_symbol(model)
    asks = [
        _scattered_policy_ask(discriminant, branched, model, definitions)
        for discriminant, branched in _branched(model, declaration).items()
        if len({(c.path, c.within) for c, _ in branched}) > 1
    ]
    return CheckOutcome(questions=tuple(a for a in asks if a is not None))
