"""application/measure.py -- measure: one run over one target.

ARCHITECTURE.ARCH-ADHERENCE.md, Use-case surface and Mechanism >
Measurement: list the target, read the sources of each measured
language, model them, merge the metrics, read the records, run every
target-level check, and cover whatever could not be read, analyzed or
answered.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from adherence.domain.checks.run import run_checks
from adherence.domain.coverage import Coverage, unmeasured, unmodelled
from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import (
    Declaration,
    DeclarationUnreadable,
    refusal_notices,
)
from adherence.domain.model import (
    CodeLanguage,
    CodeModel,
    Metrics,
    language_of,
    merged,
)
from adherence.domain.parameters import Parameters
from adherence.domain.records import DesignRecords, RecordsUnavailable
from adherence.domain.report import Report
from adherence.domain.target import Base, Head
from adherence.ports.code_model import CodeModelPort
from adherence.ports.complexity import ComplexityPort
from adherence.ports.decision import DecisionPort
from adherence.ports.duplication import DuplicationPort
from adherence.ports.records import RecordsPort
from adherence.ports.repository import Absent, RepositoryPort

UNDECLARED = RecordsUnavailable("the repository has no declaration to name a record")


@dataclass(frozen=True, slots=True)
class _Read:
    """A language's sources as read, and the paths that could not be."""

    sources: dict[str, bytes]
    coverage: tuple[Coverage, ...]


def _read_sources(
    paths: tuple[str, ...],
    language: CodeLanguage,
    at: Base | Head,
    repository: RepositoryPort,
    deadline: Deadline | None,
) -> _Read:
    sources: dict[str, bytes] = {}
    coverage: list[Coverage] = []
    for path in paths:
        if language_of(path) != language.value:
            continue
        data = repository.read(path, at, deadline)
        if isinstance(data, bytes):
            sources[path] = data
        elif isinstance(data, Absent):
            coverage.append(Coverage("listed but absent when read", path=path))
        elif isinstance(data, TimedOut):
            coverage.append(Coverage(f"{data.operation}: timed out", path=path))
        else:
            coverage.append(Coverage(f"cannot be read: {data.reason}", path=path))
    return _Read(sources, tuple(coverage))


def _model(
    read: _Read,
    language: CodeLanguage,
    analyzer: CodeModelPort,
    declaration: Declaration,
    parameters: Parameters,
    deadline: Deadline | None,
) -> CodeModel | tuple[Coverage, ...]:
    model = analyzer.model(read.sources, declaration, parameters.vocabulary, deadline)
    if isinstance(model, CodeModel):
        return model
    reason = f"the {language.value} analyzer: {model.operation}: timed out"
    return tuple(Coverage(reason, path=path) for path in sorted(read.sources))


def _metrics(answer: Metrics | TimedOut, check: str) -> Metrics | Coverage:
    if isinstance(answer, Metrics):
        return answer
    return Coverage(f"{answer.operation}: timed out", check=check)


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
        return Report.not_run(f"the declaration cannot be read: {declaration.reason}")
    paths = repository.tree(at, deadline)
    if isinstance(paths, TimedOut):
        return Report()
    models: list[CodeModel] = []
    sources: dict[str, bytes] = {}
    coverage: list[Coverage] = list(unmeasured(paths, analyzers.keys()))
    for language, analyzer in analyzers.items():
        read = _read_sources(paths, language, at, repository, deadline)
        sources.update(read.sources)
        coverage.extend(read.coverage)
        model = _model(read, language, analyzer, declaration, parameters, deadline)
        if isinstance(model, CodeModel):
            models.append(model)
        else:
            coverage.extend(model)
    for answer in (
        _metrics(complexity.measure(sources, deadline), "Complexity"),
        _metrics(duplication.measure(sources, deadline), "Duplication"),
    ):
        if isinstance(answer, Metrics):
            models.append(CodeModel(metrics=answer))
        else:
            coverage.append(answer)
    whole = merged(models)
    design: DesignRecords | RecordsUnavailable = UNDECLARED
    if declaration.declared:
        read_records = records.records(at, declaration, deadline)
        design = (
            RecordsUnavailable(f"{read_records.operation}: timed out")
            if isinstance(read_records, TimedOut)
            else read_records
        )
    checked = run_checks(whole, declaration, design, parameters)
    return Report(
        ran=checked.ran,
        findings=checked.findings,
        notices=refusal_notices(declaration),
        coverage=(*coverage, *unmodelled(whole, declaration), *checked.coverage),
    )
