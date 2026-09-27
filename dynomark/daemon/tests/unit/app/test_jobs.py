"""Contract-level job use cases (contract/v1 README, Message table and the
idempotency table): ``job.retry`` is the design's State Machine row
"FAILED -> QUEUED: user retries from chat or menu, always allowed";
``job.list`` pages a profile's jobs, optionally in one state, with a cursor
valid only for the parameters that minted it (Delivery and replay,
Pagination).
"""

import pytest

from dynomark_daemon.app.errors import UnknownRecord
from dynomark_daemon.app.jobs import list_batches_page, list_jobs_page, retry_job
from dynomark_daemon.app.pages import StaleCursor
from dynomark_daemon.domain.events import JobUpdated
from dynomark_daemon.domain.ids import BatchId, JobId, ProfileId
from dynomark_daemon.domain.job import Job, JobState
from dynomark_daemon.testing.clock import FakeClock, SequentialIds
from dynomark_daemon.testing.store import InMemoryCorpusStore
from tests._factories import make_batch, make_job

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


# --- job.list and batch.list (contract v1, Delivery and replay: Pagination) ---


def _jobs_store() -> InMemoryCorpusStore:
    store = InMemoryCorpusStore()
    states = [JobState.FAILED, JobState.QUEUED, JobState.FAILED, JobState.FAILED]
    for n, state in enumerate(states):
        store.put_job(make_job(f"job-{n}", node_id=str(n), state=state))
    store.put_job(make_job("job-b", profile_id="profile-b", state=JobState.FAILED))
    return store


def test_job_list_pages_one_profiles_jobs_in_one_state() -> None:
    """Given FAILED and QUEUED jobs of two profiles, When profile A lists FAILED
    two at a time, Then the pages hold A's FAILED jobs in order and the last
    page has no cursor."""
    store = _jobs_store()

    first = list_jobs_page(A, JobState.FAILED, None, 2, store=store)
    second = list_jobs_page(A, JobState.FAILED, first.next_cursor, 2, store=store)

    assert [j.job_id for j in first.items] == ["job-0", "job-2"]
    assert [j.job_id for j in second.items] == ["job-3"]
    assert first.next_cursor is not None and second.next_cursor is None


def test_a_cursor_is_stale_with_other_parameters_or_another_list() -> None:
    """Given a job.list cursor minted for state FAILED, When it is presented
    with another state, to batch.list, or garbled, Then it raises StaleCursor."""
    store = _jobs_store()
    cursor = list_jobs_page(A, JobState.FAILED, None, 1, store=store).next_cursor
    assert cursor is not None

    with pytest.raises(StaleCursor):
        list_jobs_page(A, None, cursor, 1, store=store)
    with pytest.raises(StaleCursor):
        list_batches_page(A, cursor, 1, store=store)
    with pytest.raises(StaleCursor):
        list_jobs_page(A, JobState.FAILED, "not-a-cursor", 1, store=store)


def test_batch_list_pages_one_profiles_batches_newest_first() -> None:
    """Given batches of two profiles, When profile A lists them two at a time,
    Then the pages hold A's batches newest first."""
    store = InMemoryCorpusStore()
    for n, created_at in enumerate([10, 30, 20]):
        store.put_batch(make_batch(f"batch-{n}", created_at=created_at))
    store.put_batch(make_batch("batch-b", created_at=40, profile_id="profile-b"))

    first = list_batches_page(A, None, 2, store=store)
    second = list_batches_page(A, first.next_cursor, 2, store=store)

    assert [b.batch.batch_id for b in first.items] == ["batch-1", "batch-2"]
    assert [b.batch.batch_id for b in second.items] == ["batch-0"]
    assert second.next_cursor is None
