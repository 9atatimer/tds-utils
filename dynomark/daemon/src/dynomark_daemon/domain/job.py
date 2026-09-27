"""The durable unit of daemon work for one ingested save."""

from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Attempts and backoff for retryable job errors; part of ``Config``."""

    attempts: int
    initial_backoff_ms: int
    max_backoff_ms: int
