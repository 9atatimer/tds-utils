"""Use case: a job is processed to an entry (DYNOMARK.DESIGN.md, Behaviors
and Interfaces; The daemon, "Enrich and index").

One attempt: capture resolved (the ingest's, else the fetch fallback),
summary and tags through ``CompletionPort``, an embedding through
``EmbeddingPort``, the entry stored through ``CorpusStorePort``.
"""

from dynomark_daemon.app.capture import capture
from dynomark_daemon.app.errors import UnknownRecord
from dynomark_daemon.domain.bookmark import (
    CaptureSource,
    CorpusEntry,
    Save,
    embedding_text,
)
from dynomark_daemon.domain.job import Job, JobState, RetryPolicy
from dynomark_daemon.ports.clock import Clock
from dynomark_daemon.ports.completion import CompletionPort
from dynomark_daemon.ports.content import ContentSourcePort
from dynomark_daemon.ports.embedding import EmbeddingPort
from dynomark_daemon.ports.errors import PortError
from dynomark_daemon.ports.store import CorpusStorePort


def _resolve_capture(
    job: Job, save: Save, *, store: CorpusStorePort, content: ContentSourcePort
) -> Save:
    """The save with its capture resolved; a fetched capture is kept."""
    if save.capture.source is not CaptureSource.NONE:
        return save
    fetched = capture(save.bookmark, content=content)
    if fetched.source is CaptureSource.NONE:
        return save
    resolved = Save(bookmark=save.bookmark, capture=fetched)
    store.put_save(job.job_id, resolved)
    return resolved


def process_job(
    job: Job,
    policy: RetryPolicy,
    *,
    store: CorpusStorePort,
    content: ContentSourcePort,
    embedding: EmbeddingPort,
    completion: CompletionPort,
    clock: Clock,
) -> CorpusEntry | Job:
    """Run one attempt of ``job`` from QUEUED or CAPTURING to ENRICHED.

    Returns:
        The stored ``CorpusEntry``; or, when the attempt failed, the job as
        stored after it (still CAPTURING for a retry, or FAILED).
    """
    save = store.get_save(job.job_id)
    if save is None:
        raise UnknownRecord(f"job {job.job_id} has no save")
    if job.state is JobState.QUEUED:
        job = job.picked_up(at=clock.now_ms())
        store.put_job(job)
    save = _resolve_capture(job, save, store=store, content=content)
    try:
        enrichment = completion.enrich(save.bookmark, save.capture)
        vector = embedding.embed(embedding_text(save.bookmark, enrichment))
    except PortError as error:
        failed = job.attempt_failed(
            str(error), retryable=error.retryable, policy=policy, at=clock.now_ms()
        )
        store.put_job(failed)
        return failed
    entry = CorpusEntry(
        identity=job.identity,
        bookmark=save.bookmark,
        capture=save.capture,
        summary=enrichment.summary,
        tags=enrichment.tags,
        embedding=vector,
        indexed_at=clock.now_ms(),
    )
    store.put_entry(entry)
    store.put_job(job.enriched(save.capture.source, at=clock.now_ms()))
    return entry
