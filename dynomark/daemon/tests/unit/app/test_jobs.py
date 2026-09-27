"""Contract-level job use cases (contract/v1 README, Message table and the
idempotency table): ``job.retry`` is the design's State Machine row
"FAILED -> QUEUED: user retries from chat or menu, always allowed";
``job.list`` pages a profile's jobs, optionally in one state, with a cursor
valid only for the parameters that minted it (Delivery and replay,
Pagination).
"""

import pytest

from dynomark_daemon.app.errors import UnknownRecord
from dynomark_daemon.app.jobs import retry_job
from dynomark_daemon.domain.events import JobUpdated
from dynomark_daemon.domain.ids import BatchId, JobId, ProfileId
from dynomark_daemon.domain.job import Job, JobState
from dynomark_daemon.testing.clock import FakeClock, SequentialIds
from dynomark_daemon.testing.store import InMemoryCorpusStore
from tests._factories import make_job

A = ProfileId("profile-a")


def _failed() -> Job:
    job = make_job(state=JobState.FAILED)
    return Job(
        job_id=job.job_id,
        profile_id=job.profile_id,
        node_id=job.node_id,
        identity=job.identity,
        state=JobState.FAILED,
        seq=4,
        attempts=3,
        backfill=False,
        updated_at=0,
        last_error="completion: connection refused",
        batch_id=BatchId("batch-1"),
    )


def _retry(store: InMemoryCorpusStore, job_id: JobId, profile: ProfileId = A) -> Job:
    return retry_job(
        job_id, profile, store=store, clock=FakeClock(start_ms=9), ids=SequentialIds()
    )


def test_retry_a_failed_job_queues_it_afresh() -> None:
    """Given a FAILED job, When the user retries it, Then it is QUEUED with a new
    seq, no attempts, no error and no batch, and a job.updated records it."""
    store = InMemoryCorpusStore()
    store.put_job(failed := _failed())

    job = _retry(store, failed.job_id)

    assert (job.state, job.seq, job.attempts) == (JobState.QUEUED, 5, 0)
    assert (job.last_error, job.batch_id, job.updated_at) == (None, None, 9)
    assert store.get_job(failed.job_id) == job
    (pending,) = store.unacked_events(A)
    assert isinstance(pending.event, JobUpdated) and pending.event.job == job


def test_retry_a_job_that_is_not_failed_changes_nothing() -> None:
    """Given a job that is not FAILED, When retried, Then it is returned
    unchanged and no event is recorded (the idempotency key is job_id)."""
    store = InMemoryCorpusStore()
    store.put_job(queued := make_job(state=JobState.PLACED))

    job = _retry(store, queued.job_id)

    assert job == queued
    assert store.unacked_events(A) == []


def test_retry_an_unknown_or_another_profiles_job_is_not_found() -> None:
    """Given no such job for this profile, When retried, Then it raises
    UnknownRecord (error not_found)."""
    store = InMemoryCorpusStore()
    store.put_job(failed := _failed())

    with pytest.raises(UnknownRecord):
        _retry(store, JobId("job-unknown"))
    with pytest.raises(UnknownRecord):
        _retry(store, failed.job_id, ProfileId("profile-b"))
