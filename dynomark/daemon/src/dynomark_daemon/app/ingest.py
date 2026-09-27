"""Use case: a save is ingested (DYNOMARK.DESIGN.md, Behaviors and Interfaces).

One durable ``Job`` per (profile, ``NodeId``, ``Identity``), persisted with
its save before the request is answered; a repeat returns the same job.
"""

from dynomark_daemon.domain.bookmark import Bookmark, Capture, Identity, Save
from dynomark_daemon.domain.ids import JobId, ProfileId
from dynomark_daemon.domain.job import Job
from dynomark_daemon.ports.clock import Clock, IdSource
from dynomark_daemon.ports.store import CorpusStorePort


def ingest(
    bookmark: Bookmark,
    capture: Capture,
    profile_id: ProfileId,
    *,
    backfill: bool = False,
    store: CorpusStorePort,
    clock: Clock,
    ids: IdSource,
) -> Job:
    """Queue the save of ``bookmark`` for ``profile_id``, once.

    Returns:
        The new ``QUEUED`` job, or the existing job of the same (profile,
        node, identity) unchanged.
    """
    identity = Identity.from_url(bookmark.url)
    existing = store.find_job(profile_id, bookmark.node_id, identity)
    if existing is not None:
        return existing
    job = Job.queued(
        JobId(ids.new_id("job")),
        profile_id=profile_id,
        node_id=bookmark.node_id,
        identity=identity,
        backfill=backfill,
        at=clock.now_ms(),
    )
    store.put_save(job.job_id, Save(bookmark=bookmark, capture=capture))
    store.put_job(job)
    return job
