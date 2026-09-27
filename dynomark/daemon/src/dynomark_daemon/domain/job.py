"""The durable unit of daemon work for one ingested save."""

from collections.abc import Iterable
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Final, Self

from dynomark_daemon.domain.bookmark import CaptureSource, Identity
from dynomark_daemon.domain.ids import BatchId, JobId, NodeId, ProfileId
from dynomark_daemon.domain.tree import Snapshot


class JobState(StrEnum):
    """The job lifecycle (DYNOMARK.DESIGN.md, State Machine)."""

    QUEUED = "QUEUED"
    CAPTURING = "CAPTURING"
    ENRICHED = "ENRICHED"
    PLACED = "PLACED"
    FILED = "FILED"
    INDEXED = "INDEXED"
    FAILED = "FAILED"


TRANSITIONS: Final = frozenset(
    {
        (JobState.QUEUED, JobState.CAPTURING),
        (JobState.CAPTURING, JobState.ENRICHED),
        (JobState.ENRICHED, JobState.INDEXED),
        (JobState.ENRICHED, JobState.PLACED),
        (JobState.PLACED, JobState.FILED),
        (JobState.QUEUED, JobState.FAILED),
        (JobState.CAPTURING, JobState.FAILED),
        (JobState.ENRICHED, JobState.FAILED),
        (JobState.PLACED, JobState.FAILED),
        (JobState.FAILED, JobState.QUEUED),
    }
)
"""The design's State Machine table, one (from, to) pair per row; the
triggers and host-role conditions are the use cases' (see each change)."""


class IllegalTransition(Exception):
    """A job change the state machine does not allow."""


@dataclass(frozen=True, slots=True)
class Job:
    """One job per (profile, ``NodeId``, ``Identity``)."""

    job_id: JobId
    profile_id: ProfileId
    node_id: NodeId
    identity: Identity
    state: JobState
    seq: int
    attempts: int
    backfill: bool
    updated_at: int
    capture_source: CaptureSource | None = None
    last_error: str | None = None
    batch_id: BatchId | None = None

    @classmethod
    def queued(
        cls,
        job_id: JobId,
        *,
        profile_id: ProfileId,
        node_id: NodeId,
        identity: Identity,
        backfill: bool,
        at: int,
    ) -> Self:
        """A new job for one save: ``QUEUED``, first ``seq``, no attempts."""
        return cls(
            job_id=job_id,
            profile_id=profile_id,
            node_id=node_id,
            identity=identity,
            state=JobState.QUEUED,
            seq=1,
            attempts=0,
            backfill=backfill,
            updated_at=at,
        )

    # --- Changes: every change moves ``seq`` and ``updated_at`` ---

    def moved_to(self, state: JobState, *, at: int) -> Self:
        """The job in ``state``, if the state machine allows the move.

        Raises:
            IllegalTransition: (``self.state``, ``state``) is not in the table.
        """
        if (self.state, state) not in TRANSITIONS:
            raise IllegalTransition(f"job {self.job_id}: {self.state} -> {state}")
        return replace(self, state=state, seq=self.seq + 1, updated_at=at)

    def picked_up(self, *, at: int) -> Self:
        """QUEUED -> CAPTURING: the job loop took the job."""
        return self.moved_to(JobState.CAPTURING, at=at)

    def enriched(self, source: CaptureSource, *, at: int) -> Self:
        """CAPTURING -> ENRICHED: capture resolved and the entry enriched."""
        moved = self.moved_to(JobState.ENRICHED, at=at)
        return replace(moved, capture_source=source, last_error=None)

    def indexed(self, *, at: int) -> Self:
        """ENRICHED -> INDEXED: searchable here, never filed (a reader host)."""
        return self.moved_to(JobState.INDEXED, at=at)

    def placed(self, *, at: int) -> Self:
        """ENRICHED -> PLACED: the placement is recorded (writer only)."""
        return self.moved_to(JobState.PLACED, at=at)

    def filed(self, *, at: int) -> Self:
        """PLACED -> FILED: the ``APPLIED`` receipt of its batch."""
        return self.moved_to(JobState.FILED, at=at)

    def failed(self, error: str, *, at: int) -> Self:
        """-> FAILED without counting an attempt: a ``PARTIAL`` or ``REJECTED``
        receipt, or a filing op the extension skipped."""
        return replace(self.moved_to(JobState.FAILED, at=at), last_error=error)

    def filed_by(self, batch_id: BatchId, *, at: int) -> Self:
        """The latest batch that files this job's node."""
        return replace(self, batch_id=batch_id, seq=self.seq + 1, updated_at=at)

    def attempt_failed(
        self, error: str, *, retryable: bool, policy: "RetryPolicy", at: int
    ) -> Self:
        """Count a failed attempt: FAILED once ``policy`` is spent or the error
        is not retryable; otherwise the job stays where it is for a retry."""
        attempts = self.attempts + 1
        exhausted = not retryable or attempts >= policy.attempts
        if exhausted:
            moved = self.moved_to(JobState.FAILED, at=at)
        else:
            moved = replace(self, seq=self.seq + 1, updated_at=at)
        return replace(moved, attempts=attempts, last_error=error)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Attempts and backoff for retryable job errors; part of ``Config``."""

    attempts: int
    initial_backoff_ms: int
    max_backoff_ms: int

    def backoff_ms(self, failed: int) -> int:
        """The delay before the retry that follows ``failed`` failed attempts:
        doubling from ``initial_backoff_ms``, capped at ``max_backoff_ms``."""
        doublings = min(max(failed - 1, 0), 62)
        return min(self.initial_backoff_ms << doublings, self.max_backoff_ms)


def is_duplicate(job: Job, filed: Iterable[Job], tree: Snapshot | None) -> bool:
    """``job``'s identity is already filed: another job of it is FILED and its
    node is present in the latest tree (contract v1, Jobs: Duplicate
    identity)."""
    if tree is None:
        return False
    return any(
        other.job_id != job.job_id
        and other.identity == job.identity
        and other.state is JobState.FILED
        and tree.node(other.node_id) is not None
        for other in filed
    )
