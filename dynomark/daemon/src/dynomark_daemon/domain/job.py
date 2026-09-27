"""The durable unit of daemon work for one ingested save."""

from dataclasses import dataclass
from enum import StrEnum

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


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Attempts and backoff for retryable job errors; part of ``Config``."""

    attempts: int
    initial_backoff_ms: int
    max_backoff_ms: int
