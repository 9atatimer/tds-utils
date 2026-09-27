"""Use cases: events are delivered, replayed and acknowledged
(DYNOMARK.DESIGN.md, Transport contract, "Delivery"; contract/v1 README,
Delivery and replay).

Use cases record events in the store (an outbox); these functions send
them. A batch whose offer cannot fit one frame is never sent: its job fails
instead (contract/v1 README, Size limits). ``offers_ready`` is the
connection's standing the transport adapter knows: mode ``full``, role
``writer``, no writer conflict, and a ``tree.snapshot`` recorded on it.
"""

from collections.abc import Iterable
from dataclasses import replace
from typing import Final

from dynomark_daemon.app.jobs import record_job_change
from dynomark_daemon.domain.batch import BatchState
from dynomark_daemon.domain.connection import HelloMode
from dynomark_daemon.domain.events import BatchOffered, ackable, deliverable
from dynomark_daemon.domain.ids import EventId, ProfileId
from dynomark_daemon.domain.job import Job, JobState
from dynomark_daemon.ports.clock import Clock, IdSource
from dynomark_daemon.ports.store import CorpusStorePort
from dynomark_daemon.ports.transport import TransportPort

OVERSIZE: Final = "batch over the 1 MiB frame limit; not offered"
"""The ``last_error`` of a job whose batch could not be offered."""


def _send(
    profile_id: ProfileId,
    mode: HelloMode,
    *,
    offers_ready: bool,
    only_new: bool,
    store: CorpusStorePort,
    transport: TransportPort,
) -> int:
    pending = deliverable(
        store.unacked_events(profile_id), mode, offers_ready=offers_ready
    )
    to_send = [p.event for p in pending if not (only_new and p.pushed)]
    # A kill after a push and before it is marked pushes it again later; the
    # extension de-duplicates by event_id and answers every offer frame.
    for event in to_send:
        transport.push(profile_id, event)
    store.mark_pushed(profile_id, [event.event_id for event in to_send])
    return len(to_send)


def deliver(
    profile_id: ProfileId,
    *,
    mode: HelloMode,
    offers_ready: bool,
    store: CorpusStorePort,
    transport: TransportPort,
) -> int:
    """Push the profile's deliverable events not pushed yet; how many."""
    return _send(
        profile_id,
        mode,
        offers_ready=offers_ready,
        only_new=True,
        store=store,
        transport=transport,
    )


def replay_events(
    profile_id: ProfileId,
    *,
    mode: HelloMode,
    offers_ready: bool,
    store: CorpusStorePort,
    transport: TransportPort,
) -> int:
    """Re-send every deliverable unacknowledged event, oldest first; how many
    (``events.replay.result`` count)."""
    return _send(
        profile_id,
        mode,
        offers_ready=offers_ready,
        only_new=False,
        store=store,
        transport=transport,
    )


def ack_events(
    profile_id: ProfileId, event_ids: Iterable[EventId], *, store: CorpusStorePort
) -> None:
    """Acknowledge job and diff events; offers, unknown and repeated ids are
    ignored."""
    store.ack_events(profile_id, ackable(store.unacked_events(profile_id), event_ids))


def fail_oversize_offers(
    profile_id: ProfileId,
    *,
    store: CorpusStorePort,
    transport: TransportPort,
    clock: Clock,
    ids: IdSource,
) -> list[Job]:
    """Withdraw every pending offer that cannot fit one frame: its event leaves
    the outbox (so it never blocks the next offer), its batch is ``REJECTED``
    and its job, if it is still waiting for it, ``FAILED`` with ``OVERSIZE``,
    in one unit of work per offer (once the event is gone nothing would
    withdraw it again); the jobs failed."""
    failed: list[Job] = []
    for pending in store.unacked_events(profile_id):
        event = pending.event
        if not isinstance(event, BatchOffered) or transport.fits(event):
            continue
        with store.atomic():
            job = _withdraw(profile_id, event, store=store, clock=clock, ids=ids)
        if job is not None:
            failed.append(job)
    return failed


def _withdraw(
    profile_id: ProfileId,
    event: BatchOffered,
    *,
    store: CorpusStorePort,
    clock: Clock,
    ids: IdSource,
) -> Job | None:
    store.ack_events(profile_id, [event.event_id])
    record = store.get_batch(event.batch.batch_id)
    if record is None:
        return None
    store.put_batch(replace(record, state=BatchState.REJECTED))
    job = None if record.job_id is None else store.get_job(record.job_id)
    if job is None or job.state is not JobState.PLACED:
        return None
    failed = job.failed(OVERSIZE, at=clock.now_ms())
    return record_job_change(failed, store=store, ids=ids)
