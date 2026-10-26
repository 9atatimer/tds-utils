"""application/measure.py -- measure: one run over one target.

ARCHITECTURE.ARCH-ADHERENCE.md, Use-case surface and Mechanism >
Measurement: list the target, read the sources of each measured
language, model them, merge the metrics, read the records, run every
target-level check, and cover whatever could not be read, analyzed or
answered.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from adherence.domain.checks.run import run_checks
from adherence.domain.coverage import (
    Coverage,
    unmeasured,
    unmeasured_in,
    unmodelled,
    unread_script,
)
from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import (
    Declaration,
    DeclarationUnreadable,
    exempted,
    refusal_notices,
    with_overrides,
)
from adherence.domain.finding import Finding, quoted
from adherence.domain.model import (
    CodeLanguage,
    CodeModel,
    Metrics,
    MetricsUnavailable,
    has_no_extension,
    language_of,
    merged,
    script_language,
    with_languages,
)
from adherence.domain.parameters import Parameters
from adherence.domain.questions import (
    Abstention,
    Ask,
    Decision,
    Judged,
    schemas,
    settled,
)
from adherence.domain.records import (
    DesignRecords,
    Radar,
    RecordsUnavailable,
)
from adherence.domain.report import (
    JUDGE_UNASKED,
    SUITE_VERSION,
    BodyDigest,
    Report,
    ReportIdentity,
    body_digest,
    fingerprint,
)
from adherence.domain.target import Base, Head
from adherence.ports.code_model import CodeModelPort
from adherence.ports.complexity import ComplexityPort
from adherence.ports.decision import DecisionPort
from adherence.ports.duplication import DuplicationPort
from adherence.ports.records import RecordsPort
from adherence.ports.repository import Absent, Refused, RepositoryPort

UNDECLARED = RecordsUnavailable("the repository has no declaration to name a record")


@dataclass(frozen=True, slots=True)
class _Read:
    """A language's sources as read, and the paths that could not be."""

    sources: dict[str, bytes]
    coverage: tuple[Coverage, ...]


@dataclass(frozen=True, slots=True)
class _Scripts:
    """The shell scripts found by shebang among files with no extension,
    read, and the coverage for every other one found or not read."""

    shell: dict[str, bytes]
    coverage: tuple[Coverage, ...]


def _read_scripts(
    paths: tuple[str, ...],
    at: Base | Head,
    repository: RepositoryPort,
    deadline: Deadline | None,
) -> _Scripts:
    """Each file with no extension, read for its shebang (Issue#638). A file
    that is refused or cut off by the deadline could be a script, so it is
    coverage with why; one gone by the time it is read is not."""
    shell: dict[str, bytes] = {}
    coverage: list[Coverage] = []
    for path in paths:
        if not has_no_extension(path):
            continue
        data = repository.read(path, at, deadline)
        if isinstance(data, TimedOut):
            coverage.append(Coverage(f"{data.operation}: timed out", path=path))
            continue
        if isinstance(data, Refused):
            coverage.append(Coverage(f"cannot be read: {data.reason}", path=path))
            continue
        if not isinstance(data, bytes):
            continue
        language = script_language(data)
        if language == CodeLanguage.SHELL.value:
            shell[path] = data
        elif language is not None:
            coverage.append(unread_script(language, path))
    return _Scripts(shell, tuple(coverage))


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


def _metrics(
    answer: Metrics | MetricsUnavailable | TimedOut, check: str
) -> Metrics | Coverage:
    if isinstance(answer, Metrics):
        return answer
    if isinstance(answer, MetricsUnavailable):
        return Coverage(answer.reason, check=check)
    return Coverage(f"{answer.operation}: timed out", check=check)


def _judge(
    asks: tuple[Ask, ...],
    judge: DecisionPort,
    parameters: Parameters,
    deadline: Deadline | None,
) -> Judged:
    """Each unit's questions put to the judge in one call, and the answers
    settled by the threshold policy."""
    findings: list[Finding] = []
    abstentions: list[Abstention] = []
    for asking in schemas(asks):
        answer = judge.decide(asking.state, asking.schema, deadline)
        if isinstance(answer, Decision):
            judged = settled(asking, answer, parameters.thresholds)
            findings.extend(judged.findings)
            abstentions.extend(judged.abstentions)
    return Judged(findings=tuple(findings), abstentions=tuple(abstentions))


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
    identity = ReportIdentity(
        suite=SUITE_VERSION,
        parameters=fingerprint(parameters),
        declaration=fingerprint(declaration),
        analyzers=tuple(sorted(language.value for language in analyzers)),
        judge=JUDGE_UNASKED,
    )
    parameters = with_overrides(parameters, declaration)
    paths = repository.tree(at, deadline)
    if isinstance(paths, TimedOut):
        return Report.not_run(f"the repository cannot be read: {paths.operation}")
    if isinstance(paths, Refused):
        return Report.not_run(f"the repository cannot be read: {paths.reason}")
    measured = {language.value for language in analyzers}
    if not any(language_of(path) in measured for path in paths):
        # Not run, and still naming every source no analyzer measures.
        return replace(
            Report.not_run(
                "no unit in a measured language "
                f"({', '.join(sorted(measured)) or 'none bound'})"
            ),
            coverage=unmeasured(paths, analyzers.keys()),
        )
    models: list[CodeModel] = []
    sources: dict[str, bytes] = {}
    coverage: list[Coverage] = list(unmeasured(paths, analyzers.keys()))
    scripts = _read_scripts(paths, at, repository, deadline)
    coverage.extend(scripts.coverage)
    if CodeLanguage.SHELL not in analyzers:
        shell = CodeLanguage.SHELL.value
        coverage.extend(unmeasured_in(shell, path) for path in sorted(scripts.shell))
    for language, analyzer in analyzers.items():
        read = _read_sources(paths, language, at, repository, deadline)
        if language is CodeLanguage.SHELL:
            read = _Read({**read.sources, **scripts.shell}, read.coverage)
        sources.update(read.sources)
        coverage.extend(read.coverage)
        model = _model(read, language, analyzer, declaration, parameters, deadline)
        if isinstance(model, CodeModel):
            models.append(model)
        else:
            coverage.extend(model)
    unmeasured_checks: set[str] = set()
    for answer in (
        _metrics(complexity.measure(sources, deadline), "Complexity"),
        _metrics(duplication.measure(sources, deadline), "Duplication"),
    ):
        if isinstance(answer, Metrics):
            models.append(CodeModel(metrics=answer))
        else:
            coverage.append(answer)
            unmeasured_checks.add(answer.check or "")
    whole = with_languages(
        merged(models), {path: CodeLanguage.SHELL.value for path in scripts.shell}
    )
    design: DesignRecords | RecordsUnavailable = UNDECLARED
    if declaration.declared:
        read_records = records.records(at, declaration, deadline)
        design = (
            RecordsUnavailable(f"{read_records.operation}: timed out")
            if isinstance(read_records, TimedOut)
            else read_records
        )
    tech: Radar | RecordsUnavailable = UNDECLARED
    if declaration.declared:
        read_radar = records.radar(at, declaration, deadline)
        tech = (
            RecordsUnavailable(f"{read_radar.operation}: timed out")
            if isinstance(read_radar, TimedOut)
            else read_radar
        )
    checked = run_checks(whole, declaration, design, parameters, radar=tech)
    judged = _judge(checked.questions, judge, parameters, deadline)
    findings, applied = exempted(
        quoted(
            (*checked.findings, *judged.findings),
            sources,
            parameters.limits.evidence_bound,
        ),
        declaration,
    )
    return Report(
        ran=tuple(c for c in checked.ran if c.name not in unmeasured_checks),
        findings=findings,
        notices=(*refusal_notices(declaration), *applied),
        coverage=(*coverage, *unmodelled(whole, declaration), *checked.coverage),
        abstentions=judged.abstentions,
        units=whole.units,
        bodies=tuple(
            BodyDigest(d.unit.path, d.unit.symbol, body_digest(d.body.text))
            for d in whole.definitions
            if d.unit.symbol is not None
        ),
        identity=identity,
        revision=at.revision,
    )
