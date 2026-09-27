"""A blocking contract v1 client for integration tests: frames over a socket."""

import json
import socket
from pathlib import Path
from typing import Final

TIMEOUT_S: Final = 5.0
JsonObject = dict[str, object]


def connect(path: Path) -> socket.socket:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(TIMEOUT_S)
    client.connect(str(path))
    return client


def send(client: socket.socket, body: bytes) -> None:
    client.sendall(len(body).to_bytes(4, "little") + body)


def _exactly(client: socket.socket, size: int) -> bytes | None:
    data = b""
    while len(data) < size:
        chunk = client.recv(size - len(data))
        if not chunk:
            return None
        data += chunk
    return data


def receive(client: socket.socket) -> JsonObject | None:
    """The next frame as a JSON object, or None when the peer closed."""
    header = _exactly(client, 4)
    if header is None:
        return None
    body = _exactly(client, int.from_bytes(header, "little"))
    if body is None:
        return None
    document = json.loads(body)
    assert isinstance(document, dict)
    return document


def answer_to(
    client: socket.socket, request_id: str
) -> tuple[JsonObject, list[JsonObject]]:
    """Frames up to the one answering ``request_id``: that answer, and the
    events that came before it."""
    events: list[JsonObject] = []
    while True:
        frame = receive(client)
        assert frame is not None, f"closed before answering {request_id}"
        if "event_id" in frame:
            events.append(frame)
            continue
        assert frame.get("re") == request_id, frame
        return frame, events


def events_until(
    client: socket.socket, predicate: "EventPredicate"
) -> list[JsonObject]:
    """Events up to and including the first that ``predicate`` accepts."""
    seen: list[JsonObject] = []
    while True:
        frame = receive(client)
        assert frame is not None, "closed while waiting for an event"
        assert "event_id" in frame, f"unexpected answer {frame}"
        seen.append(frame)
        if predicate(frame):
            return seen


class EventPredicate:
    """Matches an event by type and, optionally, a job state."""

    def __init__(self, event_type: str, state: str | None = None) -> None:
        self.event_type = event_type
        self.state = state

    def __call__(self, frame: JsonObject) -> bool:
        if frame.get("type") != self.event_type:
            return False
        job = frame.get("job")
        return self.state is None or (
            isinstance(job, dict) and job.get("state") == self.state
        )
