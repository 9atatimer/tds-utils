"""application/judge.py -- judge_change: the gate's core.

ARCHITECTURE.ARCH-ADHERENCE.md, Use-case surface and Mechanism > Judging a
change: tell what the change did, read the declaration in force, measure
the head and the base, and compare the two reports in domain/verdict.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field, replace

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
from adherence.application.load import (
    read_as_one,
    read_declarations,
    read_file,
)
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
from adherence.domain.checks.outcome import CheckOutcome
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
    RecordPaths,
    counted_landing,
    depth_first,
    directory_of,
    is_test_data,
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
from adherence.domain.verdict import UnitKey, compared, stated_units
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
) -> CodeOwners | tuple[CodeOwners, Notice] | TimedOut:
    """The base's CODEOWNERS, from the first place GitHub looks that holds
    one. No entries when none holds one; no entries and a notice naming
    the file and the reason when the first found is refused; the TimedOut
    when a read of it times out, which ends the walk."""
    for path in CODEOWNERS_PATHS:
        text = repository.read(path, base, deadline)
        if isinstance(text, TimedOut):
            return text
        if isinstance(text, Refused):
            return CodeOwners(), Notice(
                f"{path} cannot be read: {text.reason}; it names no code "
                "owner of a declaration"
            )
        if isinstance(text, bytes):
            return parse_codeowners(text)
    return CodeOwners()


def _text_at(
    commit: str, path: str, repository: RepositoryPort, deadline: Deadline | None
) -> DeclarationText | TimedOut:
    """A declaration file's bytes at a commit: None where it is absent; the
    TimedOut when the read times out, which ends the walk."""
    if not commit:
        return DeclarationUnreadable("no commit named")
    text = repository.read(path, Base(commit), deadline)
    if isinstance(text, Absent):
        return None
    if isinstance(text, Refused):
        return DeclarationUnreadable(text.reason)
    return text


def _reviewed_text(
    commit: str,
    path: str,
    hosted: Mapping[str, DeclarationText],
    repository: RepositoryPort,
    deadline: Deadline | None,
) -> DeclarationText | TimedOut:
    """A declaration file at a reviewed commit: as the code host gives it,
    which reads a PR head no checkout can fetch; from the repository when
    the code host gives none that reads; unreadable, with both reasons,
    when neither does; the TimedOut when the repository's read times out."""
    given = hosted.get(commit, DeclarationUnreadable("the code host gave none"))
    if not isinstance(given, DeclarationUnreadable):
        return given
    local = _text_at(commit, path, repository, deadline)
    if not isinstance(local, DeclarationUnreadable):
        return local
    return DeclarationUnreadable(
        f"the code host: {given.reason}; the repository: {local.reason}"
    )


def _landed(
    commit: str,
    path: str,
    answer: Landing,
    repository: RepositoryPort,
    deadline: Deadline | None,
) -> LandedRevision | TimedOut:
    """A landing with the declaration's text at it and at each commit its
    approvals reviewed; the first TimedOut, with no read after it."""
    text = _text_at(commit, path, repository, deadline)
    if isinstance(text, TimedOut):
        return text
    hosted = dict(answer.reviewed)
    reviewed: list[tuple[str, DeclarationText]] = []
    for c in sorted({a.commit for a in answer.approvals}):
        found = _reviewed_text(c, path, hosted, repository, deadline)
        if isinstance(found, TimedOut):
            return found
        reviewed.append((c, found))
    return LandedRevision(
        commit, answer, text=text, reviewed=tuple(reviewed), path=path
    )


@dataclass(frozen=True, slots=True)
class _InForce:
    """The declaration in force and what the walk to it leaves the report:
    its notices, and coverage for each file no landing of which could be
    counted, so a repository judged undeclared that way is inconclusive at
    best. `files` holds each file in force, as it reads, by path; `walked`
    every file the base's history landed."""

    declaration: Declaration | DeclarationUnreadable
    notices: tuple[Notice, ...] = ()
    coverage: tuple[Coverage, ...] = ()
    files: tuple[tuple[str, Declaration], ...] = ()
    walked: frozenset[str] = frozenset()


def _undeclared_reason(path: str) -> str:
    """Why a declaration file governs nothing: no landing of it counted."""
    if path == DECLARATION_PATH:
        return UNDECLARED
    return (
        f"no landing of {path} on the base's history carried a counted "
        f"approval; its subtree {directory_of(path)}/ is judged undeclared"
    )


def _undeclared(notices: list[Notice], reason: str, path: str) -> _InForce:
    return _InForce(
        Declaration.none,
        (*notices, Notice(reason)),
        (Coverage(reason, path=path),),
    )


@dataclass(slots=True)
class _Walk:
    """One run's walk over the declaration files' landings: the ports, and
    the base's CODEOWNERS once read, with the notices the walk has said."""

    base: Base
    repository: RepositoryPort
    reviews: ReviewPort
    deadline: Deadline | None
    notices: list[Notice]
    codeowners: CodeOwners | None = None
    owned: set[str] = field(default_factory=set)

    def owners(self, path: str) -> CodeOwners | TimedOut:
        """The base's CODEOWNERS, read once; its team and email entries for
        the file said once per file."""
        if self.codeowners is None:
            read = _codeowners(self.base, self.repository, self.deadline)
            if isinstance(read, TimedOut):
                return read
            if isinstance(read, tuple):
                read, said = read
                self.notices.append(said)
            self.codeowners = read
        if path not in self.owned:
            self.owned.add(path)
            self.notices.extend(owner_notices(self.codeowners, path))
        return self.codeowners

    def in_force(self, path: str) -> str | None | TimedOut:
        """The commit of the newest landing of the file that counts, None
        when none does; the first TimedOut, which ends the walk."""
        history = self.repository.history(path, self.base, self.deadline)
        if isinstance(history, TimedOut):
            return history
        if isinstance(history, Refused):
            self.notices.append(
                Notice(f"the history of {path} cannot be read: {history.reason}")
            )
            return None
        for commit in history:
            answer = self.reviews.approvals(commit, self.deadline, path=path)
            if isinstance(answer, TimedOut):
                return answer
            revision: LandedRevision | TimedOut = LandedRevision(
                commit, answer, path=path
            )
            codeowners = CodeOwners()
            if isinstance(answer, Landing):
                owners = self.owners(path)
                if isinstance(owners, TimedOut):
                    return owners
                codeowners = owners
                revision = _landed(commit, path, answer, self.repository, self.deadline)
            if isinstance(revision, TimedOut):
                return revision
            counting = counted_landing(revision, codeowners)
            self.notices.extend(counting.notices)
            if counting.in_force:
                return commit
        return None


def _landed_declarations(
    base: Base, repository: RepositoryPort, deadline: Deadline | None
) -> list[str] | _InForce:
    """Every declaration file at the base or ever landed on its history,
    root first; the repository judged undeclared when they cannot be
    listed."""
    paths: set[str] = set()
    for listed in (
        repository.find(DECLARATION_PATH, base, deadline),
        repository.touched(DECLARATION_PATH, base, deadline),
    ):
        if isinstance(listed, TimedOut):
            return _undeclared(
                [], f"{listed.operation}: timed out; {UNDECLARED}", DECLARATION_PATH
            )
        if isinstance(listed, Refused):
            return _undeclared(
                [],
                f"the declarations cannot be listed: {listed.reason}; "
                "the repository is judged undeclared",
                DECLARATION_PATH,
            )
        paths.update(listed)
    return depth_first(paths)


def _declaration_in_force(
    base: Base,
    repository: RepositoryPort,
    reviews: ReviewPort,
    deadline: Deadline | None,
) -> _InForce:
    """Each adherence.toml the base's history landed, settled in force on
    its own: the newest landing domain/declaration counts, read at that
    commit (a counted deletion governs nothing); a file with none governs
    nothing and is a notice, with coverage. A file a declaration in force
    above it places in the test layer is test data: never walked, never a
    notice. The files in force are read as
    one over the base's tree. A TimedOut from any port ends the walk there,
    with no port call after it, and the repository is judged undeclared."""
    walk = _Walk(base, repository, reviews, deadline, [])
    paths = _landed_declarations(base, repository, deadline)
    if isinstance(paths, _InForce):
        return paths
    files: list[tuple[str, Declaration]] = []
    coverage: list[Coverage] = []
    walked: set[str] = set()
    for path in paths:
        if is_test_data(path, [f for _, f in files]):
            continue
        commit = walk.in_force(path)
        if isinstance(commit, TimedOut):
            return _undeclared(
                walk.notices,
                f"{commit.operation}: timed out; {UNDECLARED}",
                DECLARATION_PATH,
            )
        walked.add(path)
        if commit is None:
            reason = _undeclared_reason(path)
            walk.notices.append(Notice(reason))
            coverage.append(Coverage(reason, path=path))
            continue
        read = read_file(path, Base(commit), repository=repository, deadline=deadline)
        if isinstance(read, DeclarationUnreadable):
            return _InForce(read, tuple(walk.notices), tuple(coverage))
        if read is not None:
            files.append((path, read))
    declaration = read_as_one(
        [f for _, f in files], base, repository=repository, deadline=deadline
    )
    return _InForce(
        declaration,
        tuple(walk.notices),
        tuple(coverage),
        tuple(files),
        frozenset(walked),
    )


def _proposed(
    in_force: _InForce,
    head: tuple[tuple[str, Declaration | DeclarationUnreadable], ...],
    at: Head,
    repository: RepositoryPort,
    deadline: Deadline | None,
) -> Declaration | DeclarationUnreadable:
    """The head's own revisions of the files in force, read as one: the
    only declaration a widening is taken from, since a file new at the head
    governs from the next change."""
    kept = {path for path, _ in in_force.files}
    return read_as_one(
        [read for path, read in head if path in kept],
        at,
        repository=repository,
        deadline=deadline,
    )


def _file_notices(
    in_force: _InForce,
    head: tuple[tuple[str, Declaration | DeclarationUnreadable], ...],
    merged: Declaration | DeclarationUnreadable,
    paths: Collection[str],
    created: Collection[str],
) -> tuple[Notice, ...]:
    """A notice per edit the change makes to a declaration file, each
    naming the file: an edit to one in force, as edit_notices says it; a
    file new at the head, which governs from the next change; a file in
    force the head deletes; and the head's files read as one, when only
    that cannot be read."""
    before = dict(in_force.files)
    after = dict(head)
    notices: list[Notice] = []
    for path in sorted({*before, *after}, key=lambda p: (p.count("/"), p)):
        was, now = before.get(path), after.get(path)
        if was is not None and now is not None:
            notices.extend(
                Notice(f"{path}: {n.message}")
                for n in edit_notices(
                    in_force=was,
                    proposed=now,
                    paths=paths,
                    created=created,
                )
            )
        elif was is not None:
            notices.append(
                Notice(
                    f"{path} deleted: not judged under for this change; it "
                    "takes effect from the next change"
                )
            )
        elif path not in in_force.walked and now is not None:
            unread = (
                f": it cannot be read: {now.reason}"
                if isinstance(now, DeclarationUnreadable)
                else ""
            )
            notices.append(
                Notice(
                    f"{path}: a new declaration governs from the next change{unread}"
                )
            )
    every_file_reads = not any(isinstance(r, DeclarationUnreadable) for _, r in head)
    if isinstance(merged, DeclarationUnreadable) and every_file_reads:
        notices.append(
            Notice(
                "the change's own declaration cannot be read: "
                f"{merged.reason}; it is judged under the declaration "
                "in force"
            )
        )
    return tuple(notices)


def _undeclared_creations(
    declaration: Declaration, created: Collection[str]
) -> tuple[Notice, ...]:
    """A notice per directory the change creates files in that no
    declaration governs: the top of each new undeclared subtree."""
    if not declaration.declared:
        return ()
    tops = sorted(
        {
            path.partition("/")[0] if "/" in path else "."
            for path in created
            if not declaration.governs(path)
        }
    )
    return tuple(Notice(f"created under no declaration: {top}") for top in tops)


def _scope_dirs(*declarations: Declaration) -> list[str]:
    """Every directory a records scope begins at, the root's first."""
    return sorted(
        {
            "",
            *(d for declaration in declarations for d, _ in declaration.record_scopes),
        },
        key=lambda d: (d.count("/"), d),
    )


def _records_kept(
    change: Change,
    in_force: Declaration,
    declaration: Declaration,
    records: RecordsPort,
    deadline: Deadline | None,
    bound: int,
) -> tuple[CheckOutcome, frozenset[UnitKey]]:
    """Record kept over each records scope, base under the declaration in
    force, head under the one the head is judged under, each pair read
    once; and the record units the head's records state."""
    pairs: dict[tuple[RecordPaths | None, RecordPaths | None], str] = {}
    for directory in _scope_dirs(in_force, declaration):
        probe = f"{directory}/x" if directory else "x"
        pairs.setdefault(
            (in_force.records_for(probe), declaration.records_for(probe)), directory
        )
    outcomes: list[CheckOutcome] = []
    stated: set[UnitKey] = set()
    single = len(pairs) == 1
    for base_paths, head_paths in pairs:
        head_records = _records_at(
            change.head,
            declaration if single else replace(declaration, records=head_paths),
            records,
            deadline,
        )
        base_records = _records_at(
            change.base,
            in_force if single else replace(in_force, records=base_paths),
            records,
            deadline,
        )
        outcomes.append(record_kept(base=base_records, head=head_records, bound=bound))
        stated |= stated_units(head_records)
    return (
        CheckOutcome(
            tuple(f for o in outcomes for f in o.findings),
            tuple(c for o in outcomes for c in o.coverage),
            any(o.ran for o in outcomes),
        ),
        frozenset(stated),
    )


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
    read = read_declarations(change.head, repository=repository, deadline=deadline)
    head_files = () if isinstance(read, DeclarationUnreadable) else read
    proposed = (
        read
        if isinstance(read, DeclarationUnreadable)
        else _proposed(walked, head_files, change.head, repository, deadline)
    )
    declaration = widened(in_force=in_force, proposed=proposed, created=change.created)
    head = measuring.measure(change.head, declaration, finished)
    if head.not_run_reason is not None:
        return replace(
            compared(base=Report(), head=head, change=change),
            repository=change.repository,
        )
    edits = (
        *_file_notices(
            walked,
            head_files,
            read
            if isinstance(read, DeclarationUnreadable)
            else read_as_one(
                [r for _, r in head_files],
                change.head,
                repository=repository,
                deadline=deadline,
            ),
            {u.path for u in head.units},
            change.created,
        ),
        *_undeclared_creations(declaration, change.created),
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
    kept, stated = _records_kept(
        change,
        in_force,
        declaration,
        records,
        deadline,
        parameters.limits.evidence_bound,
    )
    head = with_outcome(head, RECORD_KEPT, kept)
    head = replace(
        head,
        notices=(*head.notices, *walked.notices, *edits),
        coverage=(*head.coverage, *walked.coverage),
    )
    return replace(
        compared(base=base, head=head, change=change, stated=stated),
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
