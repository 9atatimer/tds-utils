"""Events the daemon pushes to a profile's connection, durable until acked."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from dynomark_daemon.domain.batch import WriteBatch
from dynomark_daemon.domain.connection import HelloMode
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


@dataclass(frozen=True, slots=True)
class PendingEvent:
    """An unacknowledged event and whether it was pushed live already."""

    event: Event
    pushed: bool


# --- Delivery rules (contract/v1 README, Delivery and replay) ---


def deliverable(
    pending: Sequence[PendingEvent], mode: HelloMode, *, offers_ready: bool
) -> list[PendingEvent]:
    """The unacknowledged events a connection in ``mode`` may be sent.

    ``full``: every job and diff event, plus the oldest batch offer when the
    connection is ready for offers (at most one offer outstanding per
    profile). ``read_only``: job events only. ``refused``: nothing.
    """
    if mode is HelloMode.REFUSED:
        return []
    if mode is HelloMode.READ_ONLY:
        return [p for p in pending if isinstance(p.event, JobUpdated)]
    head = next((p for p in pending if isinstance(p.event, BatchOffered)), None)
    return [
        p
        for p in pending
        if not isinstance(p.event, BatchOffered) or (offers_ready and p is head)
    ]


def ackable(
    pending: Sequence[PendingEvent], event_ids: Iterable[EventId]
) -> list[EventId]:
    """The ids ``events.ack`` acknowledges: pending job and diff events only;
    a batch offer is acknowledged by its receipt alone."""
    wanted = set(event_ids)
    return [
        p.event.event_id
        for p in pending
        if p.event.event_id in wanted and not isinstance(p.event, BatchOffered)
    ]
