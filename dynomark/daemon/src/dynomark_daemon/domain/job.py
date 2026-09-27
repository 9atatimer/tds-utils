"""The durable unit of daemon work for one ingested save."""

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Self

from dynomark_daemon.domain.bookmark import CaptureSource, Identity
from dynomark_daemon.domain.ids import BatchId, JobId, NodeId, ProfileId


class JobState(StrEnum):
    """The job lifecycle (DYNOMARK.DESIGN.md, State Machine)."""

    QUEUED = "QUEUED"
    CAPTURING = "CAPTURING"
    ENRICHED = "ENRICHED"
    PLACED = "PLACED"
    FILED = "FILED"
    INDEXED = "INDEXED"
    FAILED = "FAILED"


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

    def picked_up(self, *, at: int) -> Self:
        """QUEUED -> CAPTURING: the job loop took the job."""
        return replace(self, state=JobState.CAPTURING, seq=self.seq + 1, updated_at=at)

    def enriched(self, source: CaptureSource, *, at: int) -> Self:
        """CAPTURING -> ENRICHED: capture resolved and the entry enriched."""
        return replace(
            self,
            state=JobState.ENRICHED,
            capture_source=source,
            last_error=None,
            seq=self.seq + 1,
            updated_at=at,
        )

    def attempt_failed(
        self, error: str, *, retryable: bool, policy: "RetryPolicy", at: int
    ) -> Self:
        """Count a failed attempt: FAILED once ``policy`` is spent or the error
        is not retryable; otherwise the job stays where it is for a retry."""
        attempts = self.attempts + 1
        exhausted = not retryable or attempts >= policy.attempts
        return replace(
            self,
            state=JobState.FAILED if exhausted else self.state,
            attempts=attempts,
            last_error=error,
            seq=self.seq + 1,
            updated_at=at,
        )


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
