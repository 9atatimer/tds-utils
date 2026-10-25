"""application/measure.py -- measure: one run over one target.

ARCHITECTURE.ARCH-ADHERENCE.md, Use-case surface and Mechanism >
Measurement: list the target, read the sources of each measured
language, model them, merge the metrics, read the records, run every
target-level check.
"""

from __future__ import annotations

from collections.abc import Mapping

from adherence.domain.checks.run import run_checks
from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import Declaration, DeclarationUnreadable
from adherence.domain.model import CodeLanguage, CodeModel, Metrics, language_of, merged
from adherence.domain.parameters import Parameters
from adherence.domain.records import DesignRecords, RecordsUnavailable
from adherence.domain.report import Report
from adherence.domain.target import Base, Head
from adherence.ports.code_model import CodeModelPort
from adherence.ports.complexity import ComplexityPort
from adherence.ports.decision import DecisionPort
from adherence.ports.duplication import DuplicationPort
from adherence.ports.records import RecordsPort
from adherence.ports.repository import RepositoryPort

UNDECLARED = RecordsUnavailable("the repository has no declaration to name a record")


def _read_sources(
    paths: tuple[str, ...],
    language: CodeLanguage,
    at: Base | Head,
    repository: RepositoryPort,
    deadline: Deadline | None,
) -> dict[str, bytes]:
    sources: dict[str, bytes] = {}
    for path in paths:
        if language_of(path) != language.value:
            continue
        data = repository.read(path, at, deadline)
        if isinstance(data, bytes):
            sources[path] = data
    return sources


def measure(
    at: Base | Head,
    declaration: Declaration | DeclarationUnreadable,
    *,
    repository: RepositoryPort,
    analyzers: Mapping[CodeLanguage, CodeModelPort],
    complexity: ComplexityPort,
    duplication: DuplicationPort,
    records: RecordsPort,
    judge: DecisionPort,
    parameters: Parameters,
    deadline: Deadline | None,
) -> Report:
    """The Report of every target-level check over the target."""
    if isinstance(declaration, DeclarationUnreadable):
        return Report()
    paths = repository.tree(at, deadline)
    if isinstance(paths, TimedOut):
        return Report()
    models: list[CodeModel] = []
    sources: dict[str, bytes] = {}
    for language, analyzer in analyzers.items():
        read = _read_sources(paths, language, at, repository, deadline)
        sources.update(read)
        model = analyzer.model(read, declaration, parameters.vocabulary, deadline)
        if isinstance(model, CodeModel):
            models.append(model)
    metrics = [
        m
        for m in (
            complexity.measure(sources, deadline),
            duplication.measure(sources, deadline),
        )
        if isinstance(m, Metrics)
    ]
    whole = merged([*models, *(CodeModel(metrics=m) for m in metrics)])
    design: DesignRecords | RecordsUnavailable = UNDECLARED
    if declaration.declared:
        read_records = records.records(at, declaration, deadline)
        if not isinstance(read_records, TimedOut):
            design = read_records
    return Report(findings=run_checks(whole, declaration, design, parameters))
