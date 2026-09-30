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
    backfill: bool = False,
) -> Job:
    job = make_job(f"job-{n}", node_id=str(n), state=state)
    return replace(
        job,
        attempts=attempts,
        updated_at=updated_at,
        batch_id=batch_id,
        backfill=backfill,
    )


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


def test_a_job_whose_placement_failed_waits_its_backoff_too() -> None:
    """Given an ENRICHED job whose placement attempt failed at t, When the
    schedule is read before and after t + backoff(1), Then it is not due and
    then due: a retry while placing backs off like one while capturing."""
    failed_at = 1_000
    store = _store(_job(1, JobState.ENRICHED, attempts=1, updated_at=failed_at))
    due_at = failed_at + POLICY.backoff_ms(1)

    before = due_jobs(POLICY, due_at - 1, store=store)
    after = due_jobs(POLICY, due_at, store=store)

    assert (before.due, before.next_retry_at) == ([], due_at)
    assert [j.job_id for j in after.due] == ["job-1"]


def test_live_saves_are_due_before_backfill_in_first_queued_order() -> None:
    """Given backfill jobs queued before and among live saves, When the
    schedule is read, Then every live save comes before every backfill job,
    each class in first-queued order: a save made during a first-install
    backfill is filed next, not after thousands of old bookmarks (Goal 2)."""
    store = _store(
        _job(1, JobState.QUEUED, backfill=True),
        _job(2, JobState.CAPTURING, backfill=True),
        _job(3, JobState.QUEUED),
        _job(4, JobState.QUEUED, backfill=True),
        _job(5, JobState.ENRICHED),
    )

    schedule = due_jobs(POLICY, 1_790_000_000_000, store=store)

    assert [j.job_id for j in schedule.due] == [
        "job-3",
        "job-5",
        "job-1",
        "job-2",
        "job-4",
    ]


class _UnfinishedOnly(InMemoryCorpusStore):
    """A store on which listing every job fails the test."""

    def list_jobs(self, *, state: JobState | None = None) -> list[Job]:
        if state is None:
            raise AssertionError("the schedule read every job ever ingested")
        return super().list_jobs(state=state)


def test_the_schedule_reads_only_unfinished_jobs() -> None:
    """Given finished and unfinished jobs, When the schedule is read, Then it
    never lists every job: it is read after each job the loop runs, so its
    cost must follow the unfinished work, not the history."""
    store = _UnfinishedOnly()
    for job in (_job(1, JobState.FILED), _job(2, JobState.QUEUED)):
        store.put_job(job)

    schedule = due_jobs(POLICY, 1_790_000_000_000, store=store)

    assert [j.job_id for j in schedule.due] == ["job-2"]
