"""Use cases on jobs the extension asks for by id (contract/v1 README:
``job.retry``, ``job.list``); the State Machine row FAILED -> QUEUED.
"""

from dynomark_daemon.app.errors import UnknownRecord
from dynomark_daemon.domain.events import JobUpdated
from dynomark_daemon.domain.ids import EventId, JobId, ProfileId
from dynomark_daemon.domain.job import Job, JobState
from dynomark_daemon.ports.clock import Clock, IdSource
from dynomark_daemon.ports.store import CorpusStorePort


def record_job_change(job: Job, *, store: CorpusStorePort, ids: IdSource) -> Job:
    """Store ``job`` and its ``job.updated`` event (the outbox)."""
    store.put_job(job)
    store.put_event(
        job.profile_id, JobUpdated(event_id=EventId(ids.new_id("event")), job=job)
    )
    return job


def profile_job(job_id: JobId, profile_id: ProfileId, *, store: CorpusStorePort) -> Job:
    """The profile's job ``job_id``.

    Raises:
        UnknownRecord: no such job, or it belongs to another profile.
    """
    job = store.get_job(job_id)
    if job is None or job.profile_id != profile_id:
        raise UnknownRecord(f"profile {profile_id} has no job {job_id}")
    return job


def retry_job(
    job_id: JobId,
    profile_id: ProfileId,
    *,
    store: CorpusStorePort,
    clock: Clock,
    ids: IdSource,
) -> Job:
    """Queue a FAILED job again; any other job is returned unchanged.

    Raises:
        UnknownRecord: no such job for this profile (``not_found``).
    """
    job = profile_job(job_id, profile_id, store=store)
    if job.state is not JobState.FAILED:
        return job
    return record_job_change(job.retried(at=clock.now_ms()), store=store, ids=ids)
