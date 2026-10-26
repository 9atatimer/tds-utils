"""application/judge.py -- judge_change: the gate's core.

ARCHITECTURE.ARCH-ADHERENCE.md, Use-case surface and Mechanism > Judging a
change: tell what the change did, read the declaration in force, measure
the head and the base, and compare the two reports in domain/verdict.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from adherence.application.load import load_declaration
from adherence.application.measure import measure
from adherence.domain.checks.declared import (
    COVERED,
    RECORD_KEPT,
    covered,
    created_units,
    record_kept,
    with_outcome,
)
from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import (
    Declaration,
    DeclarationUnreadable,
    widened,
)
from adherence.domain.model import CodeLanguage
from adherence.domain.parameters import Parameters
from adherence.domain.records import DesignRecords, RecordsUnavailable
from adherence.domain.report import Report, ReportIdentity, fingerprint
from adherence.domain.target import Base, Change, Head
from adherence.domain.verdict import compared
from adherence.ports.code_model import CodeModelPort
from adherence.ports.complexity import ComplexityPort
from adherence.ports.decision import DecisionPort
from adherence.ports.duplication import DuplicationPort
from adherence.ports.records import RecordsPort
from adherence.ports.report_store import ReportStore
from adherence.ports.repository import Refused, RepositoryPort
from adherence.ports.review import ReviewPort


@dataclass(frozen=True, slots=True)
class _Measuring:
    """The ports and values every measurement of the change is given."""

    repository: RepositoryPort
    analyzers: Mapping[CodeLanguage, CodeModelPort]
    complexity: ComplexityPort
    duplication: DuplicationPort
    records: RecordsPort
    judge: DecisionPort
    parameters: Parameters
    deadline: Deadline | None

    def measure(
        self, at: Base | Head, declaration: Declaration | DeclarationUnreadable
    ) -> Report:
        return measure(
            at,
            declaration,
            repository=self.repository,
            analyzers=self.analyzers,
            complexity=self.complexity,
            duplication=self.duplication,
            records=self.records,
            judge=self.judge,
            parameters=self.parameters,
            deadline=self.deadline,
        )


def _stored_base(
    change: Change,
    in_force: Declaration,
    head: ReportIdentity | None,
    reports: ReportStore,
    deadline: Deadline | None,
) -> Report | None:
    """The base report kept under the base identity -- the head run's, with
    the digest of the declaration in force -- when one is kept and its
    identity is that one."""
    if head is None:
        return None
    identity = replace(head, declaration=fingerprint(in_force))
    kept = reports.get(
        change.repository, change.base.revision, identity.digest, deadline
    )
    if isinstance(kept, Report) and kept.identity == identity:
        return kept
    return None


def _records_at(
    at: Base | Head,
    declaration: Declaration,
    records: RecordsPort,
    deadline: Deadline | None,
) -> DesignRecords | RecordsUnavailable:
    found = records.records(at, declaration, deadline)
    if isinstance(found, TimedOut):
        return RecordsUnavailable(f"{found.operation}: timed out")
    return found


def _not_run(change: Change, reason: str) -> Report:
    return replace(
        compared(base=Report(), head=Report.not_run(reason), change=change),
        repository=change.repository,
    )


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
    reports: ReportStore,
    parameters: Parameters,
    deadline: Deadline | None,
) -> Report:
    """The change's Report: the head's findings with their provenance, the
    base findings removed, and the verdict.

    The declaration in force is the base's; which landed revision of it a
    code owner approved is read through `reviews` (task-063), and Unknown,
    the answer of every stage without a code host, leaves the landed one
    standing. The head is measured under it with the head declaration's
    widening for the files the change created. The base's report is the
    one `reports` kept under the base identity, when it kept one; else the
    base is measured again.
    """
    paths = repository.changed(change.base, change.head, deadline)
    if isinstance(paths, Refused | TimedOut):
        reason = paths.reason if isinstance(paths, Refused) else paths.operation
        return _not_run(change, f"the repository cannot be read: {reason}")
    change = replace(change, paths=paths)
    measuring = _Measuring(
        repository,
        analyzers,
        complexity,
        duplication,
        records,
        judge,
        parameters,
        deadline,
    )
    in_force = load_declaration(change.base, repository=repository, deadline=deadline)
    if not isinstance(in_force, Declaration):
        head = measuring.measure(change.head, in_force)
        return replace(
            compared(base=Report(), head=head, change=change),
            repository=change.repository,
        )
    proposed = load_declaration(change.head, repository=repository, deadline=deadline)
    declaration = widened(in_force, proposed, change.created)
    head = measuring.measure(change.head, declaration)
    if head.not_run_reason is not None:
        return replace(
            compared(base=Report(), head=head, change=change),
            repository=change.repository,
        )
    stored = _stored_base(change, in_force, head.identity, reports, deadline)
    base = stored or measuring.measure(change.base, in_force)
    found = covered(
        created_units(base=base, head=head, change=change),
        declaration,
        parameters.limits.evidence_bound,
    )
    head = with_outcome(head, COVERED, found)
    kept = record_kept(
        base=_records_at(change.base, in_force, records, deadline),
        head=_records_at(change.head, declaration, records, deadline),
        bound=parameters.limits.evidence_bound,
    )
    head = with_outcome(head, RECORD_KEPT, kept)
    return replace(
        compared(base=base, head=head, change=change), repository=change.repository
    )
