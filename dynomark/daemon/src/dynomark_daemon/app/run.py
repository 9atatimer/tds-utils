"""The job loop's step: one job driven through the design's use cases as far
as it can go now (DYNOMARK.DESIGN.md, The daemon: "Durable jobs", "Place
and file"; State Machine).

No scheduler port (Rejections): the in-process loop calls ``run_job`` for
each job that is due, and again after ``RetryPolicy.backoff_ms`` for a job
left waiting on a retry, or after the next ``tree.snapshot`` for a job
left PLACED without a batch. One ``job.updated`` event records what
changed.
"""

from typing import Final

from dynomark_daemon.app.errors import TreeNotReady, UnknownRecord
from dynomark_daemon.app.file import file
from dynomark_daemon.app.place import place
from dynomark_daemon.app.process import process_job
from dynomark_daemon.domain.batch import OutsideOwnedRoots
from dynomark_daemon.domain.events import JobUpdated
from dynomark_daemon.domain.ids import EventId
from dynomark_daemon.domain.job import Job, JobState, RetryPolicy
from dynomark_daemon.domain.placement import NoAdmissibleFolder
from dynomark_daemon.domain.roles import HostRole
from dynomark_daemon.domain.tree import OwnedRoots, TreeOutline, outline_of
from dynomark_daemon.ports.clock import Clock, IdSource
from dynomark_daemon.ports.completion import CompletionPort
from dynomark_daemon.ports.content import ContentSourcePort
from dynomark_daemon.ports.embedding import EmbeddingPort
from dynomark_daemon.ports.errors import PortError
from dynomark_daemon.ports.store import CorpusStorePort

FEEDBACK_EXAMPLES: Final = 20
"""How many recent ``MoveFeedback`` examples a placement is shown."""


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


def _place_job(
    job: Job,
    role: HostRole,
    roots: OwnedRoots,
    policy: RetryPolicy,
    *,
    store: CorpusStorePort,
    embedding: EmbeddingPort,
    completion: CompletionPort,
    clock: Clock,
) -> Job:
    entry = store.get_entry(job.identity)
    if entry is None:
        raise UnknownRecord(f"job {job.job_id} has no entry")
    try:
        place(
            entry,
            current_outline(roots, store=store),
            store.recent_feedback(limit=FEEDBACK_EXAMPLES),
            role,
            store=store,
            embedding=embedding,
            completion=completion,
            clock=clock,
        )
    except PortError as error:
        return _fail(
            job,
            error,
            retryable=error.retryable,
            policy=policy,
            store=store,
            clock=clock,
        )
    except NoAdmissibleFolder as error:
        return _fail(
            job, error, retryable=False, policy=policy, store=store, clock=clock
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
) -> Job:
    """Advance ``job`` as far as it can go now; the job as stored after."""
    start = job
    if job.state in (JobState.QUEUED, JobState.CAPTURING):
        process_job(
            job,
            policy,
            store=store,
            content=content,
            embedding=embedding,
            completion=completion,
            clock=clock,
        )
        job = _reload(job, store=store)
    if job.state is JobState.ENRICHED:
        job = _place_job(
            job,
            role,
            roots,
            policy,
            store=store,
            embedding=embedding,
            completion=completion,
            clock=clock,
        )
    if job.state is JobState.PLACED and job.batch_id is None:
        job = _file_job(job, role, roots, policy, store=store, clock=clock, ids=ids)
    if job != start:
        store.put_event(
            job.profile_id, JobUpdated(event_id=EventId(ids.new_id("event")), job=job)
        )
    return job
