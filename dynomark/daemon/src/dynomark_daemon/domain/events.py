"""Events the daemon pushes to a profile's connection, durable until acked."""

from dataclasses import dataclass

from dynomark_daemon.domain.batch import WriteBatch
from dynomark_daemon.domain.diff import TreeDiff
from dynomark_daemon.domain.ids import EventId
from dynomark_daemon.domain.job import Job


@dataclass(frozen=True, slots=True)
class JobUpdated:
    event_id: EventId
    job: Job


@dataclass(frozen=True, slots=True)
class BatchOffered:
    event_id: EventId
    batch: WriteBatch


@dataclass(frozen=True, slots=True)
class DiffProposed:
    event_id: EventId
    diff: TreeDiff


Event = JobUpdated | BatchOffered | DiffProposed
