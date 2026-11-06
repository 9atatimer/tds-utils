"""application/bounded.py -- judge_bounded: the hook's judging, within its bound.

ARCHITECTURE.ARCH-ADHERENCE.md, Use-case surface ("The hook ends within its
bound") and Mechanism > Judging a change (The hook): judge_change runs as
the worker's job, reporting the head's checks as they finish; a job that
finishes returns its Report, and a job the worker ends at the deadline
becomes the Report of the checks it finished, with every other check as
coverage, beside the run's coverage and notices it reported first
(domain/report.assemble_partial). A job that failed -- it raised,
or its process died -- is a suite that could not measure: not run, naming
why. The application reads no time
and ends nothing itself: the worker does.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from adherence.application.judge import JudgeJob
from adherence.domain.deadline import Deadline
from adherence.domain.model import CodeLanguage
from adherence.domain.parameters import Parameters
from adherence.domain.report import Report, assemble_partial, unfinished_checks
from adherence.domain.target import Change
from adherence.domain.verdict import compared
from adherence.ports.code_model import CodeModelPort
from adherence.ports.complexity import ComplexityPort
from adherence.ports.decision import DecisionPort
from adherence.ports.duplication import DuplicationPort
from adherence.ports.records import RecordsPort
from adherence.ports.report_store import ReportStore
from adherence.ports.repository import RepositoryPort
from adherence.ports.review import ReviewPort
from adherence.ports.worker import Failed, WorkerPort


def judge_bounded(
    change: Change,
    *,
    worker: WorkerPort,
    deadline: Deadline,
    repository: RepositoryPort,
    reviews: ReviewPort,
    analyzers: Mapping[CodeLanguage, CodeModelPort],
    complexity: ComplexityPort,
    duplication: DuplicationPort,
    records: RecordsPort,
    judge: DecisionPort,
    reports: ReportStore,
    parameters: Parameters,
) -> Report:
    """The change's Report, reached by the deadline: judge_change's when the
    job finishes; not run, naming why, when it failed; else the checks it
    finished with the rest as coverage and the verdict inconclusive."""
    job = JudgeJob(
        change,
        repository,
        reviews,
        dict(analyzers),
        complexity,
        duplication,
        records,
        judge,
        reports,
        parameters,
        deadline,
    )
    ran = worker.run(job, deadline)
    if isinstance(ran, Report):
        return ran
    if isinstance(ran, Failed):
        return replace(
            compared(base=Report(), head=Report.not_run(ran.reason), change=change),
            repository=change.repository,
        )
    partial = assemble_partial(
        ran.finished,
        unfinished_checks(ran.finished),
        coverage=ran.coverage,
        notices=ran.notices,
    )
    return replace(
        partial,
        reasons=(ran.reason, *partial.reasons),
        repository=change.repository,
        revision=change.head.revision,
    )
