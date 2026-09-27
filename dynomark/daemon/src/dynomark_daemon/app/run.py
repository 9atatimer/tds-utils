"""The job loop's step: one job driven through the design's use cases as far
as it can go now (DYNOMARK.DESIGN.md, The daemon: "Durable jobs", "Place
and file"; State Machine).

No scheduler port (Rejections): the in-process loop calls ``run_job`` for
each job that is due, and again after ``RetryPolicy.backoff_ms`` for a job
left waiting on a retry, or after the next ``tree.snapshot`` for a job
left PLACED without a batch. One ``job.updated`` event records what
changed.

Units of work: the model calls (enrichment inside ``process_job``, the
folder choice inside ``place``) come first, outside any unit. Everything
after the last of them -- the job's new state, its batch and offer, and
its ``job.updated`` -- is one unit, so a job is never left in a state the
loop does not run again (FAILED, INDEXED, FILED, PLACED with a batch)
without its update, nor pointing at no batch after one was offered. A
kill before that unit commits leaves the job QUEUED, CAPTURING or ENRICHED,
which the loop runs again; ``place`` has then stored a placement already,
and the rerun's ``place`` replaces it (one placement per identity).
"""

from typing import Final

from dynomark_daemon.app.errors import TreeNotReady, UnknownRecord
from dynomark_daemon.app.file import file, park
from dynomark_daemon.app.jobs import record_job_change
from dynomark_daemon.app.place import place
from dynomark_daemon.app.process import process_job
from dynomark_daemon.domain.batch import OutsideOwnedRoots
from dynomark_daemon.domain.bookmark import CorpusEntry
from dynomark_daemon.domain.job import Job, JobState, RetryPolicy, is_duplicate
from dynomark_daemon.domain.placement import (
    NoAdmissibleFolder,
    Placement,
    PlacementReason,
)
from dynomark_daemon.domain.roles import HostRole, NotWriter
from dynomark_daemon.domain.tree import OwnedRoots, TreeOutline, outline_of
from dynomark_daemon.domain.writer import WriterConflict
from dynomark_daemon.ports.clock import Clock, IdSource
from dynomark_daemon.ports.completion import CompletionPort
from dynomark_daemon.ports.content import ContentSourcePort
from dynomark_daemon.ports.embedding import EmbeddingPort
from dynomark_daemon.ports.errors import PortError
from dynomark_daemon.ports.store import CorpusStorePort

FEEDBACK_EXAMPLES: Final = 20
"""How many recent ``MoveFeedback`` examples a placement is shown."""

BACKFILL_MODEL: Final = "backfill"
"""The ``model_id`` of a placement no model chose: a backfill found in place."""


def current_outline(roots: OwnedRoots, *, store: CorpusStorePort) -> TreeOutline:
    """The ``Dynomark`` outline of the latest tree, with the stored flags."""
    tree = store.latest_tree_snapshot()
    if tree is None:
        return TreeOutline(root=roots.dynomark, folders=())
    return outline_of(tree, roots.dynomark, store.folder_flags())


def _reload(job: Job, *, store: CorpusStorePort) -> Job:
    stored = store.get_job(job.job_id)
    if stored is None:
        raise UnknownRecord(f"job {job.job_id} is not stored")
    return stored


def _fail(
    job: Job,
    error: Exception,
    *,
    retryable: bool,
    policy: RetryPolicy,
    store: CorpusStorePort,
    clock: Clock,
) -> Job:
    failed = job.attempt_failed(
        str(error), retryable=retryable, policy=policy, at=clock.now_ms()
    )
    store.put_job(failed)
    return failed


def _is_duplicate(job: Job, *, store: CorpusStorePort) -> bool:
    filed = store.list_jobs(state=JobState.FILED)
    return is_duplicate(job, filed, store.latest_tree_snapshot())


def _backfill(
    job: Job, role: HostRole, roots: OwnedRoots, *, store: CorpusStorePort, clock: Clock
) -> Job:
    """A backfill is never offered a batch (contract v1, Jobs: Backfill): on the
    writer, one already inside ``Dynomark`` is recorded as filed where it is;
    every other ends INDEXED."""
    save = store.get_save(job.job_id)
    if save is None:
        raise UnknownRecord(f"job {job.job_id} has no save")
    now = clock.now_ms()
    if role is HostRole.READER or not save.bookmark.path.is_inside(roots.dynomark):
        indexed = job.indexed(at=now)
        store.put_job(indexed)
        return indexed
    store.put_placement(
        Placement(
            identity=job.identity,
            reason=PlacementReason(
                folder=save.bookmark.path,
                neighbours=(),
                rationale="backfill: already filed here",
                feedback_ids=(),
                model_id=BACKFILL_MODEL,
            ),
            created_at=now,
        )
    )
    filed = job.placed(at=now).filed(at=now)
    store.put_job(filed)
    return filed


Chosen = Placement | PortError | NoAdmissibleFolder | None
"""What the models made of placing a job: its placement, the error that
stopped them, or ``None`` when no model places it (a backfill, a reader, a
duplicate)."""


def _choose(
    job: Job,
    role: HostRole,
    *,
    roots: OwnedRoots,
    store: CorpusStorePort,
    embedding: EmbeddingPort,
    completion: CompletionPort,
    clock: Clock,
) -> Chosen:
    """Place an ENRICHED job the writer files, before any unit of work opens
    (it calls the models)."""
    if job.backfill or role is HostRole.READER:
        return None
    entry = store.get_entry(job.identity)
    if entry is None:
        raise UnknownRecord(f"job {job.job_id} has no entry")
    if _is_duplicate(job, store=store):
        return None
    try:
        placement = place(
            entry,
            current_outline(roots, store=store),
            store.recent_feedback(limit=FEEDBACK_EXAMPLES),
            role,
            store=store,
            embedding=embedding,
            completion=completion,
            clock=clock,
        )
    except (PortError, NoAdmissibleFolder) as error:
        return error
    return None if isinstance(placement, NotWriter) else placement


def _place_job(
    job: Job,
    chosen: Chosen,
    role: HostRole,
    roots: OwnedRoots,
    policy: RetryPolicy,
    *,
    store: CorpusStorePort,
    clock: Clock,
) -> Job:
    if job.backfill:
        return _backfill(job, role, roots, store=store, clock=clock)
    if role is HostRole.READER:
        indexed = job.indexed(at=clock.now_ms())
        store.put_job(indexed)
        return indexed
    if isinstance(chosen, PortError):
        return _fail(
            job,
            chosen,
            retryable=chosen.retryable,
            policy=policy,
            store=store,
            clock=clock,
        )
    if isinstance(chosen, NoAdmissibleFolder):
        return _fail(
            job, chosen, retryable=False, policy=policy, store=store, clock=clock
        )
    placed = job.placed(at=clock.now_ms())
    store.put_job(placed)
    return placed


def _file_job(
    job: Job,
    role: HostRole,
    roots: OwnedRoots,
    policy: RetryPolicy,
    *,
    store: CorpusStorePort,
    clock: Clock,
    ids: IdSource,
) -> Job:
    placement = store.get_placement(job.identity)
    if placement is None:
        raise UnknownRecord(f"job {job.job_id} has no placement")
    try:
        if _is_duplicate(job, store=store):
            park(job, roots, role, store=store, clock=clock, ids=ids)
        else:
            file(
                placement,
                job,
                current_outline(roots, store=store),
                roots,
                role,
                store=store,
                clock=clock,
                ids=ids,
            )
    except TreeNotReady:
        return job
    except OutsideOwnedRoots as error:
        return _fail(
            job, error, retryable=False, policy=policy, store=store, clock=clock
        )
    return _reload(job, store=store)


def _awaits_filing(job: Job) -> bool:
    """Indexed and not filed yet: the point where a writer would place it."""
    if job.state is JobState.PLACED:
        return job.batch_id is None
    return job.state is JobState.ENRICHED


def run_job(
    job: Job,
    role: HostRole,
    roots: OwnedRoots,
    policy: RetryPolicy,
    *,
    store: CorpusStorePort,
    content: ContentSourcePort,
    embedding: EmbeddingPort,
    completion: CompletionPort,
    clock: Clock,
    ids: IdSource,
    conflict: WriterConflict | None = None,
) -> Job:
    """Advance ``job`` as far as it can go now; the job as stored after. On a
    writer in ``conflict`` the job is indexed, then FAILED naming it
    (contract v1, Writer marker)."""
    start = job
    if job.state in (JobState.QUEUED, JobState.CAPTURING):
        processed = process_job(
            job,
            policy,
            store=store,
            content=content,
            embedding=embedding,
            completion=completion,
            clock=clock,
            ids=ids,
        )
        job = _reload(job, store=store)
        if not isinstance(processed, CorpusEntry):
            return job  # the failed attempt is recorded with its update
    refused = conflict is not None and role is HostRole.WRITER and _awaits_filing(job)
    chosen: Chosen = None
    if job.state is JobState.ENRICHED and not refused:
        chosen = _choose(
            job,
            role,
            roots=roots,
            store=store,
            embedding=embedding,
            completion=completion,
            clock=clock,
        )
    with store.atomic():
        if conflict is not None and refused:
            job = job.failed(conflict.reason(), at=clock.now_ms())
            store.put_job(job)
        if job.state is JobState.ENRICHED:
            job = _place_job(job, chosen, role, roots, policy, store=store, clock=clock)
        if (
            job.state is JobState.PLACED
            and job.batch_id is None
            and role is HostRole.WRITER
        ):
            job = _file_job(job, role, roots, policy, store=store, clock=clock, ids=ids)
        if job != start:
            record_job_change(job, store=store, ids=ids)
    return job
