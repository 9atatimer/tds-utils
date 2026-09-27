"""Use cases: events are delivered, replayed and acknowledged
(DYNOMARK.DESIGN.md, Transport contract, "Delivery"; contract/v1 README,
Delivery and replay).

Use cases record events in the store (an outbox); these functions send
them. ``offers_ready`` is the connection's standing the transport adapter
knows: mode ``full``, role ``writer``, no writer conflict, and a
``tree.snapshot`` recorded on it.
"""

from collections.abc import Iterable

from dynomark_daemon.domain.connection import HelloMode
from dynomark_daemon.domain.events import ackable, deliverable
from dynomark_daemon.domain.ids import EventId, ProfileId
from dynomark_daemon.ports.store import CorpusStorePort
from dynomark_daemon.ports.transport import TransportPort


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
