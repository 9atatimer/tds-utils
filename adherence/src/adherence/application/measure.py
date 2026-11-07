"""application/measure.py -- measure: one run over one target.

ARCHITECTURE.ARCH-ADHERENCE.md, Use-case surface and Mechanism >
Measurement: list the target, read the sources of each measured
language, model them, merge the metrics, read the records, run every
target-level check, and cover whatever could not be read, analyzed or
answered.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import TypeVar

from adherence.application.latch import (
    Latch,
    LatchedComplexity,
    LatchedDecision,
    LatchedDuplication,
    LatchedRecords,
    LatchedRepository,
    latched_analyzers,
)
from adherence.domain.checks.run import RecordScope, each_check, gathered
from adherence.domain.coverage import (
    Coverage,
    undeclared_subtree,
    unmeasured,
    unmeasured_in,
    unmodelled,
    unread_script,
)
from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import (
    Declaration,
    DeclarationUnreadable,
    RecordPaths,
    exempted,
    refusal_notices,
    with_overrides,
)
from adherence.domain.finding import Finding, Notice, quoted
from adherence.domain.model import (
    CodeLanguage,
    CodeModel,
    Metrics,
    MetricsUnavailable,
    UnitKind,
    has_no_extension,
    language_of,
    merged,
    script_language,
    with_languages,
)
from adherence.domain.parameters import Parameters
from adherence.domain.qualities import CATALOG, Quality
from adherence.domain.questions import (
    Abstention,
    Ask,
    Availability,
    Decision,
    Judged,
    Pass,
    Rejected,
    Unavailable,
    schemas,
    settled,
    unanswered_checks,
    unasked,
    within_budget,
)
from adherence.domain.records import (
    DesignRecords,
    Radar,
    RecordsUnavailable,
)
from adherence.domain.report import (
    SUITE_VERSION,
    BodyDigest,
    FinishedCheck,
    Report,
    ReportIdentity,
    RunCoverage,
    RunNotices,
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
from adherence.ports.worker import FinishedSink

Read = TypeVar("Read")

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


def _failed(answer: Unavailable | TimedOut) -> str:
    if isinstance(answer, Unavailable):
        return f"was not asked: the judge is unavailable: {answer.reason}"
    return f"was not asked: {answer.operation}: timed out"


def _judge(
    asks: tuple[Ask, ...],
    judge: DecisionPort,
    parameters: Parameters,
    deadline: Deadline | None,
) -> tuple[Judged, Availability]:
    """Each unit's questions put to the judge in one call, and the answers
    settled by the threshold policy, within the judged-check budget, with
    the judge's availability: the bound judge's, unless it could not be
    reached. The budget is a bound judge's: with none bound, the port is
    asked once for why, and every question is coverage naming that, never
    the budget. After the judge first fails -- unavailable or out of time
    -- it is not asked again, and every question left is coverage; a call
    the judge rejects is coverage, and the next is still asked."""
    bound = judge.availability() is Availability.AVAILABLE
    budget = parameters.limits.judged_budget if bound else len(asks)
    asked, over_budget = within_budget(asks, budget)
    findings: list[Finding] = []
    passes: list[Pass] = []
    abstentions: list[Abstention] = []
    coverage: list[Coverage] = list(over_budget)
    failure: Unavailable | TimedOut | None = None
    for asking in schemas(asked):
        answer = failure or judge.decide(asking.state, asking.schema, deadline)
        if isinstance(answer, Decision):
            judged = settled(asking, answer, parameters.thresholds)
            findings.extend(judged.findings)
            passes.extend(judged.passes)
            abstentions.extend(judged.abstentions)
            coverage.extend(judged.coverage)
        elif isinstance(answer, Rejected):
            coverage.extend(
                unasked(asking, f"was rejected by the judge: {answer.reason}")
            )
        else:
            failure = answer
            coverage.extend(unasked(asking, _failed(answer)))
    availability = (
        Availability.UNAVAILABLE
        if isinstance(failure, Unavailable)
        else judge.availability()
    )
    judged = Judged(tuple(findings), tuple(passes), tuple(abstentions), tuple(coverage))
    return judged, availability


def reported(
    found: Iterable[Coverage], finished: FinishedSink | None
) -> tuple[Coverage, ...]:
    """Run-level coverage as it is found, reported to `finished` at once, so
    a run ended later -- inside an analyzer, say -- still names it."""
    items = tuple(found)
    if finished is not None and items:
        finished(RunCoverage(items))
    return items


def noticed(found: Iterable[Notice], finished: FinishedSink | None) -> None:
    """Run-level notices as they are known, reported to `finished` at once,
    so a run ended later still says them."""
    items = tuple(found)
    if finished is not None and items:
        finished(RunNotices(items))


def _with_judged(check: FinishedCheck, judged: Judged) -> FinishedCheck:
    """A check that asked the judge, with what the judge's answers made of
    its questions: its judged findings, passes, abstentions and the
    questions left unanswered."""
    name = check.check.name
    return replace(
        check,
        findings=(
            *check.findings,
            *(f for f in judged.findings if f.check == check.check),
        ),
        coverage=(*check.coverage, *(c for c in judged.coverage if c.check == name)),
        passes=tuple(p for p in judged.passes if p.check == check.check),
        abstentions=tuple(a for a in judged.abstentions if a.check == check.check),
        questions=(),
    )


def _as_reported(
    check: FinishedCheck,
    sources: Mapping[str, bytes],
    declaration: Declaration,
    parameters: Parameters,
    unmeasured: set[str] | frozenset[str],
) -> tuple[FinishedCheck, tuple[Notice, ...]]:
    """A finished check as the Report shows it: evidence quoted within the
    bound, exemptions applied, and not run when its metrics were not; and
    the notice of each exemption applied."""
    findings, applied = exempted(
        quoted(check.findings, sources, parameters.limits.evidence_bound),
        declaration,
    )
    ran = check.ran and check.check.name not in unmeasured
    return replace(check, findings=findings, ran=ran), applied


@dataclass(frozen=True, slots=True)
class _Modelled:
    """The target's sources read and modelled: each language's model and
    the metrics, every source read, the shell scripts found by shebang, the
    run's coverage so far, and the checks whose metrics were not measured."""

    models: tuple[CodeModel, ...]
    sources: dict[str, bytes]
    shell: dict[str, bytes]
    coverage: tuple[Coverage, ...]
    unmeasured_checks: frozenset[str]


def _identity(
    parameters: Parameters,
    declaration: Declaration,
    analyzers: Mapping[CodeLanguage, CodeModelPort],
    judge: DecisionPort,
) -> ReportIdentity:
    return ReportIdentity(
        suite=SUITE_VERSION,
        parameters=fingerprint(parameters),
        declaration=fingerprint(declaration),
        analyzers=tuple(sorted(language.value for language in analyzers)),
        judge=judge.availability().value,
    )


def _listed(
    paths: tuple[str, ...] | Refused | TimedOut,
    analyzers: Mapping[CodeLanguage, CodeModelPort],
    identity: ReportIdentity,
    at: Base | Head,
) -> tuple[str, ...] | Report:
    """The target's paths, or the Report of a run that cannot go on: cut
    off listing them, every check coverage; refused, not run; or holding no
    unit in a measured language, not run and naming every source no
    analyzer measures."""
    if isinstance(paths, TimedOut):
        reason = f"{paths.operation}: timed out"
        return Report(
            coverage=tuple(
                Coverage(reason, check=c.name)
                for c in CATALOG
                if c.quality is not Quality.DECLARED
            ),
            identity=identity,
            revision=at.revision,
        )
    if isinstance(paths, Refused):
        return Report.not_run(f"the repository cannot be read: {paths.reason}")
    measured = {language.value for language in analyzers}
    if not any(language_of(path) in measured for path in paths):
        return replace(
            Report.not_run(
                "no unit in a measured language "
                f"({', '.join(sorted(measured)) or 'none bound'})"
            ),
            coverage=unmeasured(paths, analyzers.keys()),
        )
    return paths


def _languages_modelled(
    paths: tuple[str, ...],
    at: Base | Head,
    *,
    repository: RepositoryPort,
    analyzers: Mapping[CodeLanguage, CodeModelPort],
    declaration: Declaration,
    parameters: Parameters,
    deadline: Deadline | None,
    finished: FinishedSink | None,
) -> _Modelled:
    """Each measured language's sources read and modelled, the shell
    scripts among them, each gap reported to `finished` as it is found."""
    models: list[CodeModel] = []
    sources: dict[str, bytes] = {}
    coverage = list(reported(unmeasured(paths, analyzers.keys()), finished))
    scripts = _read_scripts(paths, at, repository, deadline)
    coverage.extend(reported(scripts.coverage, finished))
    if CodeLanguage.SHELL not in analyzers:
        shell = CodeLanguage.SHELL.value
        unread = (unmeasured_in(shell, path) for path in sorted(scripts.shell))
        coverage.extend(reported(unread, finished))
    for language, analyzer in analyzers.items():
        read = _read_sources(paths, language, at, repository, deadline)
        if language is CodeLanguage.SHELL:
            read = _Read({**read.sources, **scripts.shell}, read.coverage)
        sources.update(read.sources)
        coverage.extend(reported(read.coverage, finished))
        model = _model(read, language, analyzer, declaration, parameters, deadline)
        if isinstance(model, CodeModel):
            models.append(model)
        else:
            coverage.extend(reported(model, finished))
    return _Modelled(
        tuple(models), sources, scripts.shell, tuple(coverage), frozenset()
    )


def _with_metrics(
    modelled: _Modelled,
    complexity: ComplexityPort,
    duplication: DuplicationPort,
    deadline: Deadline | None,
    finished: FinishedSink | None,
) -> _Modelled:
    """The modelled target with its complexity and clones; a metric not
    measured is coverage, reported at once, and its check unmeasured."""
    models = list(modelled.models)
    coverage = list(modelled.coverage)
    unmeasured_checks: set[str] = set()
    for answer in (
        _metrics(complexity.measure(modelled.sources, deadline), "Complexity"),
        _metrics(duplication.measure(modelled.sources, deadline), "Duplication"),
    ):
        if isinstance(answer, Metrics):
            models.append(CodeModel(metrics=answer))
        else:
            coverage.extend(reported((answer,), finished))
            unmeasured_checks.add(answer.check or "")
    return replace(
        modelled,
        models=tuple(models),
        coverage=tuple(coverage),
        unmeasured_checks=frozenset(unmeasured_checks),
    )


def _unless_timed_out(answer: Read | TimedOut) -> Read | RecordsUnavailable:
    if isinstance(answer, TimedOut):
        return RecordsUnavailable(f"{answer.operation}: timed out")
    return answer


def _design_inputs(
    records: RecordsPort,
    at: Base | Head,
    declaration: Declaration,
    deadline: Deadline | None,
) -> tuple[DesignRecords | RecordsUnavailable, Radar | RecordsUnavailable]:
    """The design records and the radar the declaration names; for an
    undeclared repository, neither is read."""
    if not declaration.declared:
        return UNDECLARED, UNDECLARED
    return (
        _unless_timed_out(records.records(at, declaration, deadline)),
        _unless_timed_out(records.radar(at, declaration, deadline)),
    )


def _record_scopes(
    model: CodeModel,
    declaration: Declaration,
    records: RecordsPort,
    at: Base | Head,
    deadline: Deadline | None,
) -> tuple[RecordScope, ...]:
    """The model's files grouped by the design record and radar their
    nearest governing declarations name, each group's read once, its
    declaration naming that group's own pair -- a sub-project's, when that
    is the one governing declaration naming them, never only the root's."""
    groups: dict[tuple[RecordPaths | None, str | None], set[str]] = {}
    for unit in model.units:
        if unit.kind is UnitKind.FILE:
            key = (declaration.records_for(unit.path), declaration.radar_for(unit.path))
            groups.setdefault(key, set()).add(unit.path)
    scopes: list[RecordScope] = []
    for (paths, radar), files in groups.items():
        scoped = replace(
            declaration, records=paths, radar=radar, record_scopes=(), radar_scopes=()
        )
        design, tech = _design_inputs(records, at, scoped, deadline)
        scopes.append(RecordScope(frozenset(files), scoped, design, tech))
    return tuple(scopes)


def _scoped_inputs(
    model: CodeModel,
    declaration: Declaration,
    records: RecordsPort,
    at: Base | Head,
    deadline: Deadline | None,
) -> tuple[
    tuple[RecordScope, ...],
    DesignRecords | RecordsUnavailable,
    Radar | RecordsUnavailable,
]:
    """The records scopes, when the model's files name two or more pairs,
    and the records and radar the run's checks are given: with one pair,
    that pair's own, read once; with none (no file), the declaration's."""
    scopes = _record_scopes(model, declaration, records, at, deadline)
    if scopes:
        return (scopes if len(scopes) > 1 else ()), scopes[0].records, scopes[0].radar
    design, tech = _design_inputs(records, at, declaration, deadline)
    return scopes, design, tech


def _governed(
    paths: tuple[str, ...], declaration: Declaration
) -> tuple[tuple[str, ...], tuple[Coverage, ...]]:
    """The paths a governing declaration reaches, and the coverage of each
    it does not: a path in an undeclared subtree has no adherence, so it is
    never modelled, no check reads it and Covered never names it. Every
    path of an undeclared repository is read as before."""
    if not declaration.declared:
        return paths, ()
    governed = tuple(p for p in paths if declaration.governs(p))
    return governed, undeclared_subtree(sorted(set(paths) - set(governed)))


def _bodies(model: CodeModel) -> tuple[BodyDigest, ...]:
    """Each named definition's body digest, by which a rename is told."""
    return tuple(
        BodyDigest(d.unit.path, d.unit.symbol, body_digest(d.body.text))
        for d in model.definitions
        if d.unit.symbol is not None
    )


def _report(
    check: FinishedCheck,
    finished: FinishedSink,
    sources: Mapping[str, bytes],
    declaration: Declaration,
    parameters: Parameters,
    unmeasured_checks: frozenset[str],
) -> None:
    """A check to `finished` as the Report will show it, after the notices
    of the exemptions it applied."""
    shown, applied = _as_reported(
        check, sources, declaration, parameters, unmeasured_checks
    )
    noticed(applied, finished)
    finished(shown)


def measure_reporting(
    at: Base | Head,
    declaration: Declaration | DeclarationUnreadable,
    *,
    finished: FinishedSink | None,
    repository: RepositoryPort,
    analyzers: Mapping[CodeLanguage, CodeModelPort],
    complexity: ComplexityPort,
    duplication: DuplicationPort,
    records: RecordsPort,
    judge: DecisionPort,
    parameters: Parameters,
    deadline: Deadline | None,
) -> Report:
    """measure, reporting each check to `finished` as it finishes, its
    evidence quoted and its exemptions applied as the Report will have
    them, and each notice as soon as it is known: the job judge_bounded
    runs reports the head's checks this way."""
    if isinstance(declaration, DeclarationUnreadable):
        return Report.not_run(f"the declaration cannot be read: {declaration.reason}")
    noticed(refusal_notices(declaration), finished)
    latch = Latch()
    repository = LatchedRepository(repository, latch)
    analyzers = latched_analyzers(latch, analyzers=analyzers)
    judge = LatchedDecision(judge, latch)
    identity = _identity(parameters, declaration, analyzers, judge)
    parameters = with_overrides(parameters, declaration)
    paths = _listed(repository.tree(at, deadline), analyzers, identity, at)
    if isinstance(paths, Report):
        return paths
    paths, ungoverned = _governed(paths, declaration)
    reported(ungoverned, finished)
    modelled = _with_metrics(
        _languages_modelled(
            paths,
            at,
            repository=repository,
            analyzers=analyzers,
            declaration=declaration,
            parameters=parameters,
            deadline=deadline,
            finished=finished,
        ),
        LatchedComplexity(complexity, latch),
        LatchedDuplication(duplication, latch),
        deadline,
        finished,
    )
    whole = with_languages(
        merged(modelled.models),
        {path: CodeLanguage.SHELL.value for path in modelled.shell},
    )
    scopes, design, tech = _scoped_inputs(
        whole, declaration, LatchedRecords(records, latch), at, deadline
    )
    reported(unmodelled(whole, declared=declaration.declared), finished)
    sources, unmeasured_checks = modelled.sources, modelled.unmeasured_checks
    done: list[FinishedCheck] = []
    for check in each_check(
        whole, declaration, design, parameters, radar=tech, scopes=scopes
    ):
        done.append(check)
        if finished is not None and not check.questions:
            _report(
                check, finished, sources, declaration, parameters, unmeasured_checks
            )
    checked = gathered(tuple(done))
    judged, availability = _judge(checked.questions, judge, parameters, deadline)
    unrun = unmeasured_checks | unanswered_checks(checked.questions, judged)
    if finished is not None:
        # A check that asked the judge finishes once the judge has answered.
        for check in (c for c in done if c.questions):
            judged_check = _with_judged(check, judged)
            _report(judged_check, finished, sources, declaration, parameters, unrun)
    findings, applied = exempted(
        quoted(
            (*checked.findings, *judged.findings),
            sources,
            parameters.limits.evidence_bound,
        ),
        declaration,
    )
    return Report(
        ran=tuple(c for c in checked.ran if c.name not in unrun),
        findings=findings,
        notices=(*refusal_notices(declaration), *applied),
        coverage=(
            *ungoverned,
            *modelled.coverage,
            *unmodelled(whole, declared=declaration.declared),
            *checked.coverage,
            *judged.coverage,
        ),
        abstentions=judged.abstentions,
        passes=judged.passes,
        units=whole.units,
        bodies=_bodies(whole),
        identity=replace(identity, judge=availability.value),
        revision=at.revision,
    )


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
    """The Report of every target-level check over the target. Once any
    port answers TimedOut, no port is asked anything more: what is left is
    coverage."""
    return measure_reporting(
        at,
        declaration,
        repository=repository,
        analyzers=analyzers,
        complexity=complexity,
        duplication=duplication,
        records=records,
        judge=judge,
        parameters=parameters,
        deadline=deadline,
        finished=None,
    )
