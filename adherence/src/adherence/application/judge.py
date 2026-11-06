"""application/judge.py -- judge_change: the gate's core.

ARCHITECTURE.ARCH-ADHERENCE.md, Use-case surface and Mechanism > Judging a
change: tell what the change did, read the declaration in force, measure
the head and the base, and compare the two reports in domain/verdict.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from adherence.application.latch import (
    Latch,
    LatchedComplexity,
    LatchedDecision,
    LatchedDuplication,
    LatchedRecords,
    LatchedReports,
    LatchedRepository,
    LatchedReviews,
    latched_analyzers,
)
from adherence.application.load import load_declaration
from adherence.application.measure import measure_reporting, noticed, reported
from adherence.domain.checks.declared import (
    COVERED,
    RECORD_KEPT,
    covered,
    created_units,
    edit_notices,
    record_kept,
    with_outcome,
)
from adherence.domain.coverage import Coverage
from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import (
    CODEOWNERS_PATHS,
    DECLARATION_PATH,
    CodeOwners,
    Declaration,
    DeclarationText,
    DeclarationUnreadable,
    LandedRevision,
    Landing,
    counted_landing,
    owner_notices,
    parse_codeowners,
    widened,
)
from adherence.domain.finding import Notice
from adherence.domain.model import CodeLanguage
from adherence.domain.parameters import Parameters
from adherence.domain.qualities import CATALOG
from adherence.domain.records import DesignRecords, RecordsUnavailable
from adherence.domain.report import (
    Report,
    ReportIdentity,
    assemble_partial,
    fingerprint,
)
from adherence.domain.target import Base, Change, Head
from adherence.domain.verdict import compared, stated_units
from adherence.ports.code_model import CodeModelPort
from adherence.ports.complexity import ComplexityPort
from adherence.ports.decision import DecisionPort
from adherence.ports.duplication import DuplicationPort
from adherence.ports.records import RecordsPort
from adherence.ports.report_store import ReportStore
from adherence.ports.repository import Absent, Refused, RepositoryPort
from adherence.ports.review import ReviewPort
from adherence.ports.worker import FinishedSink

UNMEASURABLE = (
    "the base cannot be measured under the head's suite, declaration, "
    "measured languages and judge availability"
)
UNDECLARED = (
    f"no landing of {DECLARATION_PATH} on the base's history carried a counted "
    "approval; the repository is judged undeclared"
)


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
        self,
        at: Base | Head,
        declaration: Declaration | DeclarationUnreadable,
        finished: FinishedSink | None = None,
    ) -> Report:
        return measure_reporting(
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
            finished=finished,
        )


def _base_report(
    change: Change,
    in_force: Declaration,
    head: ReportIdentity,
    reports: ReportStore,
    measuring: _Measuring,
) -> Report:
    """The base's report under the base identity -- the head run's, with the
    digest of the declaration in force: the one `reports` kept under it, or
    else the base measured again; not run, naming what differs, when the
    base cannot be measured under it."""
    identity = replace(head, declaration=fingerprint(in_force))
    kept = reports.get(
        change.repository, change.base.revision, identity.digest, measuring.deadline
    )
    if isinstance(kept, Report) and kept.identity == identity:
        return kept
    measured = measuring.measure(change.base, in_force)
    if measured.not_run_reason is not None:
        return Report.not_run(f"{UNMEASURABLE}: {measured.not_run_reason}")
    if measured.identity != identity:
        differs = (
            identity.differences(measured.identity)
            if measured.identity is not None
            else ("identity",)
        )
        return Report.not_run(f"{UNMEASURABLE}: it differs in {', '.join(differs)}")
    return measured


def _records_at(
    at: Base | Head,
    declaration: Declaration,
    records: RecordsPort,
    deadline: Deadline | None,
) -> DesignRecords | RecordsUnavailable:
    """The records at the target: a record present there counts, whatever
    status-like line it carries (design skill, Lifecycle is metadata)."""
    found = records.records(at, declaration, deadline)
    if isinstance(found, TimedOut):
        return RecordsUnavailable(f"{found.operation}: timed out", unread=True)
    return found


def _codeowners(
    base: Base, repository: RepositoryPort, deadline: Deadline | None
) -> tuple[CodeOwners, tuple[Notice, ...]] | TimedOut:
    """The base's CODEOWNERS, from the first place GitHub looks that holds
    one, with the notices it leaves the walk: its team and email entries,
    each no owner. No entries when none holds one; no entries and a notice
    naming the file and the reason when the first found is refused; the
    TimedOut when a read of it times out, which ends the walk."""
    for path in CODEOWNERS_PATHS:
        text = repository.read(path, base, deadline)
        if isinstance(text, TimedOut):
            return text
        if isinstance(text, Refused):
            return CodeOwners(), (
                Notice(
                    f"{path} cannot be read: {text.reason}; it names no code "
                    f"owner of {DECLARATION_PATH}"
                ),
            )
        if isinstance(text, bytes):
            owners = parse_codeowners(text)
            return owners, owner_notices(owners)
    return CodeOwners(), ()


def _text_at(
    commit: str, repository: RepositoryPort, deadline: Deadline | None
) -> DeclarationText | TimedOut:
    """adherence.toml's bytes at a commit: None where it is absent; the
    TimedOut when the read times out, which ends the walk."""
    if not commit:
        return DeclarationUnreadable("no commit named")
    text = repository.read(DECLARATION_PATH, Base(commit), deadline)
    if isinstance(text, Absent):
        return None
    if isinstance(text, Refused):
        return DeclarationUnreadable(text.reason)
    return text


def _reviewed_text(
    commit: str,
    hosted: Mapping[str, DeclarationText],
    repository: RepositoryPort,
    deadline: Deadline | None,
) -> DeclarationText | TimedOut:
    """adherence.toml at a reviewed commit: as the code host gives it, which
    reads a PR head no checkout can fetch; from the repository when the
    code host gives none that reads; unreadable, with both reasons, when
    neither does; the TimedOut when the repository's read times out."""
    given = hosted.get(commit, DeclarationUnreadable("the code host gave none"))
    if not isinstance(given, DeclarationUnreadable):
        return given
    local = _text_at(commit, repository, deadline)
    if not isinstance(local, DeclarationUnreadable):
        return local
    return DeclarationUnreadable(
        f"the code host: {given.reason}; the repository: {local.reason}"
    )


def _landed(
    commit: str,
    answer: Landing,
    repository: RepositoryPort,
    deadline: Deadline | None,
) -> LandedRevision | TimedOut:
    """A landing with the declaration's text at it and at each commit its
    approvals reviewed; the first TimedOut, with no read after it."""
    text = _text_at(commit, repository, deadline)
    if isinstance(text, TimedOut):
        return text
    hosted = dict(answer.reviewed)
    reviewed: list[tuple[str, DeclarationText]] = []
    for c in sorted({a.commit for a in answer.approvals}):
        found = _reviewed_text(c, hosted, repository, deadline)
        if isinstance(found, TimedOut):
            return found
        reviewed.append((c, found))
    return LandedRevision(commit, answer, text=text, reviewed=tuple(reviewed))


@dataclass(frozen=True, slots=True)
class _InForce:
    """The declaration in force and what the walk to it leaves the report:
    its notices, and coverage when no landing could be counted, so a
    repository judged undeclared that way is inconclusive at best."""

    declaration: Declaration | DeclarationUnreadable
    notices: tuple[Notice, ...] = ()
    coverage: tuple[Coverage, ...] = ()


def _undeclared(notices: list[Notice], reason: str) -> _InForce:
    return _InForce(
        Declaration.none,
        (*notices, Notice(reason)),
        (Coverage(reason, path=DECLARATION_PATH),),
    )


def _declaration_in_force(
    base: Base,
    repository: RepositoryPort,
    reviews: ReviewPort,
    deadline: Deadline | None,
) -> _InForce:
    """The newest landing of adherence.toml on the base's history that
    domain/declaration counts in force, and the walk's notices; the
    repository judged undeclared, with coverage, when none is or the walk
    cannot be made; a TimedOut from any port ends the walk there, with no
    port call after it. A base with no landing of it at all is
    undeclared."""
    history = repository.history(DECLARATION_PATH, base, deadline)
    if isinstance(history, Refused | TimedOut):
        why = history.reason if isinstance(history, Refused) else "timed out"
        return _undeclared(
            [],
            f"the history of {DECLARATION_PATH} cannot be read: {why}; "
            "the repository is judged undeclared",
        )
    if not history:
        return _InForce(Declaration.none)
    notices: list[Notice] = []
    codeowners: CodeOwners | None = None
    for commit in history:
        answer = reviews.approvals(commit, deadline)
        if isinstance(answer, TimedOut):
            return _undeclared(notices, f"{answer.operation}: timed out; {UNDECLARED}")
        revision: LandedRevision | TimedOut = LandedRevision(commit, answer)
        if isinstance(answer, Landing):
            if codeowners is None:
                read = _codeowners(base, repository, deadline)
                if isinstance(read, TimedOut):
                    return _undeclared(
                        notices, f"{read.operation}: timed out; {UNDECLARED}"
                    )
                codeowners, said = read
                notices.extend(said)
            revision = _landed(commit, answer, repository, deadline)
        if isinstance(revision, TimedOut):
            return _undeclared(
                notices, f"{revision.operation}: timed out; {UNDECLARED}"
            )
        counting = counted_landing(revision, codeowners or CodeOwners())
        notices.extend(counting.notices)
        if counting.in_force:
            declaration = load_declaration(
                Base(commit), repository=repository, deadline=deadline
            )
            return _InForce(declaration, tuple(notices))
    return _undeclared(notices, UNDECLARED)


def _not_run(change: Change, reason: str) -> Report:
    return replace(
        compared(base=Report(), head=Report.not_run(reason), change=change),
        repository=change.repository,
    )


@dataclass(frozen=True, slots=True)
class JudgeJob:
    """judge_change over one change, as a job a worker runs: a plain value,
    so a worker can hand it to a child process."""

    change: Change
    repository: RepositoryPort
    reviews: ReviewPort
    analyzers: Mapping[CodeLanguage, CodeModelPort]
    complexity: ComplexityPort
    duplication: DuplicationPort
    records: RecordsPort
    judge: DecisionPort
    reports: ReportStore
    parameters: Parameters
    deadline: Deadline | None

    def __call__(self, finished: FinishedSink | None) -> Report:
        """judge_change, reporting each of the head's checks to `finished`
        as it finishes, and each notice as soon as it is known: the job
        judge_bounded runs."""
        return _judged(self, finished)


def _judged(job: JudgeJob, finished: FinishedSink | None) -> Report:
    """The change's Report: the head's findings with their provenance, the
    base findings removed, and the verdict.

    The declaration in force is the newest landed revision of
    adherence.toml on the base's history whose landing domain/declaration
    counts: a code owner's approval read through `reviews`, against the
    base's CODEOWNERS; Unknown, the answer of every stage without a code
    host, leaves the landed one standing, and in CI a walk that finds none
    judges the repository undeclared. The head is measured under it with
    the head declaration's widening for the files the change created. The
    base's report is the one `reports` kept under the base identity, when
    it kept one; else the base is measured again. Once any port answers
    TimedOut, no port is asked anything more: what is left is coverage.
    """
    change, parameters, deadline = job.change, job.parameters, job.deadline
    latch = Latch()
    repository = LatchedRepository(job.repository, latch)
    reviews = LatchedReviews(job.reviews, latch)
    analyzers = latched_analyzers(latch, analyzers=job.analyzers)
    complexity = LatchedComplexity(job.complexity, latch)
    duplication = LatchedDuplication(job.duplication, latch)
    records = LatchedRecords(job.records, latch)
    judge = LatchedDecision(job.judge, latch)
    reports = LatchedReports(job.reports, latch)
    paths = repository.changed(change.base, change.head, deadline)
    if isinstance(paths, TimedOut):
        # Cut off before anything was measured: every check is coverage.
        return replace(
            assemble_partial((), CATALOG, reason=f"{paths.operation}: timed out"),
            repository=change.repository,
            revision=change.head.revision,
        )
    if isinstance(paths, Refused):
        return _not_run(change, f"the repository cannot be read: {paths.reason}")
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
    walked = _declaration_in_force(change.base, repository, reviews, deadline)
    noticed(walked.notices, finished)
    reported(walked.coverage, finished)
    in_force = walked.declaration
    if not isinstance(in_force, Declaration):
        head = measuring.measure(change.head, in_force)
        head = replace(head, notices=(*head.notices, *walked.notices))
        return replace(
            compared(base=Report(), head=head, change=change),
            repository=change.repository,
        )
    proposed = load_declaration(change.head, repository=repository, deadline=deadline)
    declaration = widened(in_force=in_force, proposed=proposed, created=change.created)
    head = measuring.measure(change.head, declaration, finished)
    if head.not_run_reason is not None:
        return replace(
            compared(base=Report(), head=head, change=change),
            repository=change.repository,
        )
    edits = edit_notices(
        in_force=in_force,
        proposed=proposed,
        paths={u.path for u in head.units},
        created=change.created,
    )
    noticed(edits, finished)
    base = (
        _base_report(change, in_force, head.identity, reports, measuring)
        if head.identity is not None
        else measuring.measure(change.base, in_force)
    )
    if latch.first is not None and base.not_run_reason is None:
        # A base measured after the run was cut off is not the base: what
        # the head could not finish would read as removed or introduced.
        base = Report.not_run(f"{UNMEASURABLE}: {latch.first.operation}: timed out")
    found = covered(
        created_units(base=base, head=head, change=change),
        declaration,
        parameters.limits.evidence_bound,
    )
    head = with_outcome(head, COVERED, found)
    head_records = _records_at(change.head, declaration, records, deadline)
    kept = record_kept(
        base=_records_at(change.base, in_force, records, deadline),
        head=head_records,
        bound=parameters.limits.evidence_bound,
    )
    head = with_outcome(head, RECORD_KEPT, kept)
    head = replace(
        head,
        notices=(*head.notices, *walked.notices, *edits),
        coverage=(*head.coverage, *walked.coverage),
    )
    return replace(
        compared(
            base=base, head=head, change=change, stated=stated_units(head_records)
        ),
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
    base findings removed, and the verdict (JudgeJob)."""
    job = JudgeJob(
        change,
        repository,
        reviews,
        analyzers,
        complexity,
        duplication,
        records,
        judge,
        reports,
        parameters,
        deadline,
    )
    return job(None)
