"""The job loop's schedule (DYNOMARK.DESIGN.md, The daemon: "Durable jobs --
retried per RetryPolicy on a retryable error"; Rejections: "A scheduler
port -- ... an in-process loop with RetryPolicy as a value").

``due_jobs`` says which jobs the loop runs now and when the next retry
falls due; a job interrupted by a daemon restart is simply due again.
"""

from dataclasses import replace

from dynomark_daemon.app.loop import due_jobs
from dynomark_daemon.domain.ids import BatchId
from dynomark_daemon.domain.job import Job, JobState, RetryPolicy
from dynomark_daemon.testing.store import InMemoryCorpusStore
from tests._factories import make_job

POLICY = RetryPolicy(attempts=3, initial_backoff_ms=1_000, max_backoff_ms=60_000)


def _job(
    n: int,
    state: JobState,
    *,
    attempts: int = 0,
    updated_at: int = 0,
    batch_id: BatchId | None = None,
) -> Job:
    job = make_job(f"job-{n}", node_id=str(n), state=state)
    return replace(job, attempts=attempts, updated_at=updated_at, batch_id=batch_id)


def _store(*jobs: Job) -> InMemoryCorpusStore:
    store = InMemoryCorpusStore()
    for job in jobs:
        store.put_job(job)
    return store


def test_due_jobs_are_every_unfinished_job_not_waiting_on_anything() -> None:
    """Given jobs in every state, When the schedule is read, Then QUEUED, an
    interrupted CAPTURING, ENRICHED and a PLACED job with no batch are due, in
    first-queued order; a PLACED job with a batch waits for its receipt, and
    FILED, INDEXED and FAILED are finished."""
    store = _store(
        _job(1, JobState.FILED),
        _job(2, JobState.QUEUED),
        _job(3, JobState.CAPTURING),
        _job(4, JobState.ENRICHED),
        _job(5, JobState.PLACED),
        _job(6, JobState.PLACED, batch_id=BatchId("batch-6")),
        _job(7, JobState.INDEXED),
        _job(8, JobState.FAILED),
    )

    schedule = due_jobs(POLICY, 1_790_000_000_000, store=store)

    assert [j.job_id for j in schedule.due] == ["job-2", "job-3", "job-4", "job-5"]
    assert schedule.next_retry_at is None


def test_a_job_waiting_on_a_retry_is_due_after_its_backoff() -> None:
    """Given a CAPTURING job whose second attempt failed at t, When the schedule
    is read before and after t + backoff(2), Then it is not due and then due,
    and the schedule names when it falls due."""
    failed_at = 1_000
    waiting = _job(1, JobState.CAPTURING, attempts=2, updated_at=failed_at)
    store = _store(waiting)
    due_at = failed_at + POLICY.backoff_ms(2)

    before = due_jobs(POLICY, due_at - 1, store=store)
    after = due_jobs(POLICY, due_at, store=store)

    assert (before.due, before.next_retry_at) == ([], due_at)
    assert [j.job_id for j in after.due] == ["job-1"]
