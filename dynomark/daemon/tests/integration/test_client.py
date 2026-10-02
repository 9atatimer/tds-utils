"""The e2e's socket client takes events that beat their answer (issue #370).

Events interleave freely with answers (contract v1, Envelope), so the event
a request causes can arrive before that request's answer. Which one the
daemon writes first is a race, so the e2e alone cannot pin this: here the
reading side is non-blocking, and a read the client should not make fails
at once instead of waiting out the socket timeout.
"""

import json
import socket
from collections.abc import Iterator

import pytest

from tests import _client as client
from tests._client import EventPredicate, JsonObject
from tests.integration.test_daemon_e2e import _jobs_until

pytestmark = pytest.mark.integration

OFFER: JsonObject = {"event_id": "e-1", "type": "batch.offer", "batch": {}}
FILED: JsonObject = {
    "event_id": "e-2",
    "type": "job.updated",
    "job": {"job_id": "job-1", "state": "FILED"},
}


@pytest.fixture
def pair() -> Iterator[tuple[socket.socket, socket.socket]]:
    """(reader, writer): the reader raises rather than waits on an empty
    socket."""
    reader, writer = socket.socketpair()
    reader.setblocking(False)
    with reader, writer:
        yield reader, writer


def test_events_through_takes_the_event_from_early_without_reading(
    pair: tuple[socket.socket, socket.socket],
) -> None:
    """Given the offer already among the events before an answer, When the
    client waits for an offer, Then it returns it and reads nothing more."""
    reader, _ = pair

    seen = client.events_through(reader, EventPredicate("batch.offer"), [OFFER])

    assert seen == [OFFER]


def test_events_through_reads_on_when_early_has_no_match(
    pair: tuple[socket.socket, socket.socket],
) -> None:
    """Given no offer before the answer, When the client waits for one, Then
    it reads on and returns the early events followed by the offer."""
    reader, writer = pair
    client.send(writer, json.dumps(OFFER).encode())

    seen = client.events_through(reader, EventPredicate("batch.offer"), [FILED])

    assert seen == [FILED, OFFER]


def test_jobs_until_counts_job_events_that_came_before_an_answer(
    pair: tuple[socket.socket, socket.socket],
) -> None:
    """Given a job's FILED event among the events before an answer, When the
    test waits for that job to be FILED, Then it returns without reading."""
    reader, _ = pair

    _jobs_until(reader, {"job-1": "FILED"}, [FILED])
