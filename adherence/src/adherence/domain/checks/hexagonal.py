"""domain/checks/hexagonal.py -- the core depends on no mechanism.

Grep, Arrow, Swap and Change (DESIGN.ARCH-ADHERENCE.md, The Qualities
table: Hexagonal), each a pure function over the CodeModel.
"""

from __future__ import annotations

from dataclasses import dataclass

from adherence.domain.checks.outcome import CheckOutcome
from adherence.domain.declaration import Declaration, layer_of
from adherence.domain.finding import Evidence, Finding
from adherence.domain.model import AccessKind, CodeModel, Layer, ReferenceKind
from adherence.domain.parameters import Parameters, Vocabulary
from adherence.domain.qualities import catalog_check
from adherence.domain.records import DesignRecords, RecordsUnavailable

# --- Constants ---------------------------------------------------------------

GREP = catalog_check("Grep")
CORE = frozenset({Layer.DOMAIN, Layer.APPLICATION})


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


def _mechanisms(model: CodeModel, vocabulary: Vocabulary) -> list[_Hit]:
    """Every vendor import, environment read and model id in the model."""
    return [
        *(
            _Hit(e.path, e.line, e.imported, e.text)
            for e in model.imports
            if e.imported_path is None and names_vendor(e.imported, vocabulary)
        ),
        *(
            _Hit(a.path, a.line, a.target, a.target)
            for a in model.accesses
            if a.kind is AccessKind.ENVIRONMENT
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
    findings: list[Finding] = []
    for hit in _mechanisms(model, parameters.vocabulary):
        layer = layer_of(hit.path, hit.line, declaration, model.regions)
        unit = model.unit_at(hit.path, hit.line)
        if layer in CORE and unit is not None:
            findings.append(
                Finding(
                    GREP,
                    unit,
                    layer,
                    hit.subject,
                    Evidence(hit.path, hit.line, hit.text),
                )
            )
    return CheckOutcome(tuple(findings))
