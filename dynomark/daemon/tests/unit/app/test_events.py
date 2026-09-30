"""Transport contract, Delivery: "Events are durable on the daemon until
acknowledged; on connect the extension asks for everything unacknowledged"
(DYNOMARK.DESIGN.md), as contract/v1 pins it (Delivery and replay; One
batch at a time; Connection lifecycle, the read-only and refused modes).
"""

from collections.abc import Callable
from dataclasses import replace

import pytest

from dynomark_daemon.app.events import (
    ack_events,
    deliver,
    fail_oversize_offers,
    replay_events,
)
from dynomark_daemon.domain.batch import BatchState
from dynomark_daemon.domain.connection import HelloMode
from dynomark_daemon.domain.events import (
    BatchOffered,
    DiffProposed,
    Event,
    JobUpdated,
)
from dynomark_daemon.domain.ids import BatchId, EventId, ProfileId
from dynomark_daemon.domain.job import JobState
from dynomark_daemon.testing.clock import FakeClock, SequentialIds
from dynomark_daemon.testing.store import InMemoryCorpusStore
from dynomark_daemon.testing.transport import RecordingTransport
from tests._crash import DyingStore
from tests._factories import make_batch, make_diff, make_job

A, B = ProfileId("profile-a"), ProfileId("profile-b")
FULL = HelloMode.FULL


def _job_event(n: int) -> JobUpdated:
    return JobUpdated(event_id=EventId(f"evt-job-{n}"), job=make_job())


def _offer(n: int) -> BatchOffered:
    return BatchOffered(
        event_id=EventId(f"evt-offer-{n}"), batch=make_batch(f"batch-{n}").batch
    )


def _store_with(*events: Event, profile: ProfileId = A) -> InMemoryCorpusStore:
    store = InMemoryCorpusStore()
    for event in events:
        store.put_event(profile, event)
    return store


def test_replay_resends_every_unacknowledged_event_oldest_first() -> None:
    """Given two unacknowledged job events, When replayed, acknowledged in part
    and replayed again, Then both are re-sent oldest first with their count,
    then only the one still unacknowledged."""
    first, second = _job_event(1), _job_event(2)
    store, transport = _store_with(first, second), RecordingTransport()

    count = replay_events(
        A, mode=FULL, offers_ready=True, store=store, transport=transport
    )
    ack_events(A, [first.event_id], store=store)
    again = replay_events(
        A, mode=FULL, offers_ready=True, store=store, transport=transport
    )

    assert (count, again) == (2, 1)
    assert transport.events_for(A) == [first, second, second]


def test_ack_naming_a_batch_offer_leaves_it_unacknowledged() -> None:
    """Given an offered batch, When events.ack names its event id, Then it is
    ignored: only a receipt acknowledges an offer."""
    offer = _offer(1)
    store, transport = _store_with(offer), RecordingTransport()

    ack_events(A, [offer.event_id], store=store)

    replay_events(A, mode=FULL, offers_ready=True, store=store, transport=transport)
    assert transport.events_for(A) == [offer]


def test_only_the_oldest_unacknowledged_offer_is_delivered() -> None:
    """Given two offered batches, When replayed on a ready connection, Then only
    the oldest is sent (at most one batch.offer unacknowledged per profile);
    on a connection not ready for offers, none is."""
    first, second = _offer(1), _offer(2)
    store = _store_with(first, _job_event(1), second)

    ready, not_ready = RecordingTransport(), RecordingTransport()
    replay_events(A, mode=FULL, offers_ready=True, store=store, transport=ready)
    replay_events(A, mode=FULL, offers_ready=False, store=store, transport=not_ready)

    assert ready.events_for(A) == [first, _job_event(1)]
    assert not_ready.events_for(A) == [_job_event(1)]


def test_read_only_mode_sends_only_job_updates_and_refused_sends_nothing() -> None:
    """Given job, diff and offer events, When replayed in read_only mode, Then
    only job.updated is sent; in refused mode, nothing is."""
    job = _job_event(1)
    diff = DiffProposed(event_id=EventId("evt-diff-1"), diff=make_diff())
    store = _store_with(job, diff, _offer(1))

    read_only, refused = RecordingTransport(), RecordingTransport()
    replay_events(
        A, mode=HelloMode.READ_ONLY, offers_ready=True, store=store, transport=read_only
    )
    replay_events(
        A, mode=HelloMode.REFUSED, offers_ready=True, store=store, transport=refused
    )

    assert read_only.events_for(A) == [job]
    assert refused.pushed == []


def test_deliver_pushes_each_new_event_once_while_replay_resends() -> None:
    """Given a new event, When delivered twice, Then it is pushed once (live
    delivery), and a replay still re-sends it until it is acknowledged."""
    job = _job_event(1)
    store, transport = _store_with(job), RecordingTransport()

    pushed = [
        deliver(A, mode=FULL, offers_ready=True, store=store, transport=transport)
        for _ in range(2)
    ]
    replay_events(A, mode=FULL, offers_ready=True, store=store, transport=transport)

    assert pushed == [1, 0]
    assert transport.events_for(A) == [job, job]


def test_events_go_only_to_the_profile_they_belong_to() -> None:
    """Given an event of profile A, When profile B replays or acknowledges it,
    Then B gets nothing and A still holds it."""
    job = _job_event(1)
    store, transport = _store_with(job), RecordingTransport()

    ack_events(B, [job.event_id], store=store)
    replay_events(B, mode=FULL, offers_ready=True, store=store, transport=transport)
    replay_events(A, mode=FULL, offers_ready=True, store=store, transport=transport)

    assert transport.events_for(B) == []
    assert transport.events_for(A) == [job]


# --- A batch that cannot fit one frame (contract v1, Size limits) ---


def _fits_unless(batch_id: str) -> Callable[[Event], bool]:
    def fits(event: Event) -> bool:
        return not (
            isinstance(event, BatchOffered) and event.batch.batch_id == batch_id
        )

    return fits


def test_an_offer_that_cannot_fit_a_frame_fails_its_job_and_the_next_is_offered() -> (
    None
):
    """Given the oldest offered batch does not fit the 1 MiB frame, When offers
    are delivered, Then it is never sent, its job is FAILED with a last_error
    saying so (and a job.updated is sent), the batch is REJECTED, and the next
    batch is offered instead."""
    job = replace(make_job(state=JobState.PLACED), batch_id=BatchId("batch-1"))
    store = _store_with(_offer(1), _offer(2))
    store.put_job(job)
    store.put_batch(replace(make_batch("batch-1"), job_id=job.job_id))
    store.put_batch(make_batch("batch-2"))
    transport = RecordingTransport(fits=_fits_unless("batch-1"))

    failed = fail_oversize_offers(
        A,
        store=store,
        transport=transport,
        clock=FakeClock(start_ms=5),
        ids=SequentialIds(),
    )
    deliver(A, mode=FULL, offers_ready=True, store=store, transport=transport)

    after = store.get_job(job.job_id)
    assert after is not None and after.state is JobState.FAILED
    assert after.last_error is not None and "1 MiB" in after.last_error
    assert failed == [after]
    record = store.get_batch(BatchId("batch-1"))
    assert record is not None and record.state is BatchState.REJECTED
    pushed = transport.events_for(A)
    offered = [e.batch.batch_id for e in pushed if isinstance(e, BatchOffered)]
    assert offered == ["batch-2"]
    assert [e.job for e in pushed if isinstance(e, JobUpdated)] == [after]


def test_offers_that_fit_are_left_alone() -> None:
    """Given an offered batch that fits, When oversize offers are failed, Then
    nothing changes and it is still offered."""
    store, transport = _store_with(_offer(1)), RecordingTransport()
    store.put_batch(make_batch("batch-1"))

    failed = fail_oversize_offers(
        A,
        store=store,
        transport=transport,
        clock=FakeClock(start_ms=5),
        ids=SequentialIds(),
    )
    deliver(A, mode=FULL, offers_ready=True, store=store, transport=transport)

    assert failed == []
    assert transport.events_for(A) == [_offer(1)]


def test_an_oversize_offer_withdrawn_when_the_daemon_is_killed_fails_its_job() -> None:
    """Given the daemon was killed while withdrawing an oversize offer, after
    the offer's event was acknowledged and before its batch was REJECTED,
    When the restarted daemon withdraws oversize offers again, Then the job
    is FAILED and the batch REJECTED instead of the job waiting forever on a
    batch nothing offers."""
    job = replace(make_job(state=JobState.PLACED), batch_id=BatchId("batch-1"))
    store = DyingStore()
    store.put_event(A, _offer(1))
    store.put_job(job)
    store.put_batch(replace(make_batch("batch-1"), job_id=job.job_id))
    transport = RecordingTransport(fits=_fits_unless("batch-1"))

    def withdraw() -> None:
        fail_oversize_offers(
            A,
            store=store,
            transport=transport,
            clock=FakeClock(start_ms=5),
            ids=SequentialIds(),
        )

    store.kill_at("put_batch")
    with pytest.raises(SystemExit):
        withdraw()
    withdraw()

    after = store.get_job(job.job_id)
    assert after is not None and after.state is JobState.FAILED
    record = store.get_batch(BatchId("batch-1"))
    assert record is not None and record.state is BatchState.REJECTED
    assert [p.event for p in store.unacked_events(A)] == [
        JobUpdated(event_id=EventId("event-1"), job=after)
    ]
