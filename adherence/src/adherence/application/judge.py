"""application/judge.py -- judge_change: the gate's core.

ARCHITECTURE.ARCH-ADHERENCE.md, Use-case surface and Mechanism > Judging a
change: tell what the change did, read the declaration in force, measure
the head and the base, and compare the two reports in domain/verdict.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from adherence.application.load import load_declaration
from adherence.application.measure import measure
from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.model import CodeLanguage
from adherence.domain.parameters import Parameters
from adherence.domain.report import Report
from adherence.domain.target import Change
from adherence.domain.verdict import compared
from adherence.ports.code_model import CodeModelPort
from adherence.ports.complexity import ComplexityPort
from adherence.ports.decision import DecisionPort
from adherence.ports.duplication import DuplicationPort
from adherence.ports.records import RecordsPort
from adherence.ports.repository import Refused, RepositoryPort
from adherence.ports.review import ReviewPort


def judge_change(
    change: Change,
    *,
    repository: RepositoryPort,
    reviews: ReviewPort,
    analyzers: Mapping[CodeLanguage, CodeModelPort],
    complexity: ComplexityPort,
    duplication: DuplicationPort,
    records: RecordsPort,
    judge: DecisionPort,
    parameters: Parameters,
    deadline: Deadline | None,
) -> Report:
    """The change's Report: the head's findings with their provenance, the
    base findings removed, and the verdict.

    The declaration in force is the base's; which landed revision of it a
    code owner approved is read through `reviews` (task-063), and Unknown,
    the answer of every stage without a code host, leaves the landed one
    standing.
    """
    paths = repository.changed(change.base, change.head, deadline)
    if isinstance(paths, Refused | TimedOut):
        reason = paths.reason if isinstance(paths, Refused) else paths.operation
        return compared(
            Report(),
            Report.not_run(f"the repository cannot be read: {reason}"),
            change,
        )
    change = replace(change, paths=paths)
    in_force = load_declaration(change.base, repository=repository, deadline=deadline)
    head = measure(
        change.head,
        in_force,
        repository=repository,
        analyzers=analyzers,
        complexity=complexity,
        duplication=duplication,
        records=records,
        judge=judge,
        parameters=parameters,
        deadline=deadline,
    )
    base = measure(
        change.base,
        in_force,
        repository=repository,
        analyzers=analyzers,
        complexity=complexity,
        duplication=duplication,
        records=records,
        judge=judge,
        parameters=parameters,
        deadline=deadline,
    )
    return compared(base, head, change)
