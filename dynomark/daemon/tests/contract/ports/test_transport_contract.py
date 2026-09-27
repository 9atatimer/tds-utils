"""The recording TransportPort fake: what the daemon pushed, to whom.

Design: Transport contract, "Direction -- Daemon -> extension: responses
by id, plus unsolicited events (job finished, batch ready)";
contract/v1/README.md, "Events go only to a connection of the profile they
belong to". Use-case tests assert on the pushes the fake recorded.
"""

import pytest

from dynomark_daemon.domain.events import BatchOffered, JobUpdated
from dynomark_daemon.domain.ids import EventId, ProfileId
from dynomark_daemon.ports.transport import TransportPort
from dynomark_daemon.testing.transport import RecordingTransport
from tests._factories import make_batch, make_job

pytestmark = pytest.mark.contract

A, B = ProfileId("profile-a"), ProfileId("profile-b")


def test_push_records_every_event_in_order_with_its_profile() -> None:
    """Given pushes to two profiles, When recorded, Then pushed lists each
    (profile, event) in the order pushed."""
    job_done = JobUpdated(event_id=EventId("evt-1"), job=make_job())
    offer = BatchOffered(event_id=EventId("evt-2"), batch=make_batch().batch)
    port: TransportPort = (fake := RecordingTransport())

    port.push(A, job_done)
    port.push(B, offer)

    assert fake.pushed == [(A, job_done), (B, offer)]


def test_events_for_a_profile_holds_only_that_profiles_events() -> None:
    """Given events for two profiles, When one profile's events are read, Then
    none of the other's appear (events go only to their own profile)."""
    fake = RecordingTransport()
    mine = JobUpdated(event_id=EventId("evt-1"), job=make_job())
    fake.push(A, mine)
    fake.push(B, JobUpdated(event_id=EventId("evt-2"), job=make_job("job-2")))

    assert fake.events_for(A) == [mine]
