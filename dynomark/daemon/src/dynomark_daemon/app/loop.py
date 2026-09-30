"""The job loop's schedule (DYNOMARK.DESIGN.md, The daemon: "Durable jobs";
Rejections: no scheduler port -- an in-process loop with ``RetryPolicy``
as a value).

The loop runs ``run_job`` on every due job, then waits until the next
retry falls due or something wakes it (an ingest, a retry, a snapshot).
"""

from dataclasses import dataclass
from typing import Final

from dynomark_daemon.domain.job import Job, JobState, RetryPolicy
from dynomark_daemon.ports.store import CorpusStorePort


@dataclass(frozen=True, slots=True)
class Schedule:
    """The jobs to run now, live saves first, and when the earliest job
    waiting on a retry falls due (``None`` when none waits)."""

    due: list[Job]
    next_retry_at: int | None


def _retry_at(job: Job, policy: RetryPolicy) -> int | None:
    """When a job waiting on a retry -- of its capture or of its placement --
    may run again; ``None`` if it does not wait (a job interrupted before any
    failed attempt is due at once)."""
    if job.state in (JobState.CAPTURING, JobState.ENRICHED) and job.attempts > 0:
        return job.updated_at + policy.backoff_ms(job.attempts)
    return None


UNFINISHED_STATES: Final = (
    JobState.QUEUED,
    JobState.CAPTURING,
    JobState.ENRICHED,
    JobState.PLACED,
)
"""The states a job the loop may still run can be in."""


def unfinished(job: Job) -> bool:
    """The loop still has work for ``job`` (it is not waiting on a receipt)."""
    if job.state is JobState.PLACED:
        return job.batch_id is None
    return job.state in UNFINISHED_STATES


def due_jobs(policy: RetryPolicy, now: int, *, store: CorpusStorePort) -> Schedule:
    """Which jobs the loop runs at ``now``: every unfinished job not waiting
    on a retry or on its batch's receipt, live saves before backfill, each
    in first-queued order. Reads only the unfinished jobs: the loop asks
    again after every job it runs."""
    due: list[Job] = []
    waits: list[int] = []
    for job in filter(unfinished, store.list_jobs_in(UNFINISHED_STATES)):
        retry_at = _retry_at(job, policy)
        if retry_at is not None and retry_at > now:
            waits.append(retry_at)
        else:
            due.append(job)
    due.sort(key=lambda job: job.backfill)  # stable: first-queued within each
    return Schedule(due=due, next_retry_at=min(waits, default=None))
