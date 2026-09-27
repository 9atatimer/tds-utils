"""The daemon's unix-socket transport (contract/v1/README.md: Framing,
Endpoint, Connection lifecycle, Envelope; Design: Security Considerations,
"Transport exposure -- the daemon's unix socket is owner-only; no TCP
port"). Real sockets in a temp directory; a fake-backed dispatcher.
"""

import json
import socket
import stat
import threading
from pathlib import Path

import pytest

from dynomark_daemon.adapters.socket_server import (
    DaemonAlreadyRunning,
    SocketUnavailable,
)
from dynomark_daemon.domain.bookmark import Embedding
from dynomark_daemon.domain.chat import DraftAnswer
from dynomark_daemon.domain.config import ModelInfo
from dynomark_daemon.domain.diff import DiffKind, DiffProposal
from dynomark_daemon.domain.tree import TreeOutline
from dynomark_daemon.testing.completion import ScriptedCompletion
from dynomark_daemon.testing.embedding import HashingEmbedding
from tests import _client as client
from tests import _wire as wire
from tests._server import build_server, running
from tests.contract.golden import load_object, valid_files

pytestmark = pytest.mark.integration


def _socket(tmp_path: Path) -> Path:
    return tmp_path / "state" / "dynomark" / "daemon.sock"


def test_the_socket_and_its_directory_are_owner_only(tmp_path: Path) -> None:
    """Given no state directory, When the server starts, Then the directory is
    0700 and the socket 0600."""
    path = _socket(tmp_path)

    with running(build_server(path)):
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_ISSOCK(path.stat().st_mode)


def test_hello_then_a_request_is_answered_by_its_id(tmp_path: Path) -> None:
    """Given a running server, When a client says hello and asks for status,
    Then each is answered, in turn, by its id."""
    path = _socket(tmp_path)
    with running(build_server(path)), client.connect(path) as conn:
        client.send(conn, wire.hello())
        greeting, _ = client.answer_to(conn, "h-1")
        client.send(conn, wire.body("status", "s-1"))
        status, _ = client.answer_to(conn, "s-1")

    assert (greeting["type"], greeting["mode"], greeting["role"]) == (
        "hello.result",
        "full",
        "writer",
    )
    assert status["type"] == "status.result"


def _requests() -> list[dict[str, object]]:
    documents = [load_object(path) for path in valid_files()]
    return [d for d in documents if "id" in d and d.get("type") != "hello"]


def test_every_request_of_the_contract_is_answered_exactly_once(
    tmp_path: Path,
) -> None:
    """Given a full connection, When every valid example request of contract v1
    is sent, Then each gets exactly one answer with its id: its result type or
    an error of the closed code set."""
    path = _socket(tmp_path)
    requests = _requests()
    answers: dict[str, str] = {}
    with running(build_server(path)), client.connect(path) as conn:
        client.send(conn, wire.hello())
        client.answer_to(conn, "h-1")
        for n, request in enumerate(requests):
            request_id = f"ex-{n}"
            client.send(conn, json.dumps({**request, "id": request_id}).encode())
            answer, _ = client.answer_to(conn, request_id)
            answers[str(request["type"])] = str(answer["type"])

    assert len(requests) > 20
    for request_type, answer_type in answers.items():
        assert answer_type in (f"{request_type}.result", "error"), request_type


@pytest.mark.parametrize(
    "header",
    [b"\x00\x00\x00\x00", (33_554_432 + 1).to_bytes(4, "little")],
    ids=["zero", "over-32-MiB"],
)
def test_a_bad_length_closes_the_connection_without_an_answer(
    tmp_path: Path, header: bytes
) -> None:
    """Given a connection, When a frame header says 0 or more than 32 MiB, Then
    the daemon closes it without answering."""
    path = _socket(tmp_path)
    with running(build_server(path)), client.connect(path) as conn:
        conn.sendall(header)

        assert client.receive(conn) is None


def test_a_newer_connection_of_a_profile_supersedes_the_older(tmp_path: Path) -> None:
    """Given profile A connected, When A connects again and says hello, Then the
    older connection gets error superseded (re null) and is closed, and the
    newer one is served."""
    path = _socket(tmp_path)
    with (
        running(build_server(path)),
        client.connect(path) as old,
        client.connect(path) as new,
    ):
        client.send(old, wire.hello("h-old"))
        client.answer_to(old, "h-old")
        client.send(new, wire.hello("h-new"))
        client.answer_to(new, "h-new")

        superseded = client.receive(old)
        closed = client.receive(old)
        client.send(new, wire.body("status", "s-1"))
        status, _ = client.answer_to(new, "s-1")

    assert superseded is not None
    assert (superseded["type"], superseded["code"], superseded["re"]) == (
        "error",
        "superseded",
        None,
    )
    assert closed is None and status["type"] == "status.result"


def test_connections_of_different_profiles_coexist(tmp_path: Path) -> None:
    """Given profile A connected, When profile B says hello on another
    connection, Then both are still served."""
    path = _socket(tmp_path)
    with (
        running(build_server(path)),
        client.connect(path) as a,
        client.connect(path) as b,
    ):
        client.send(a, wire.hello("h-a", profile="profile-a"))
        client.answer_to(a, "h-a")
        client.send(b, wire.hello("h-b", profile="profile-b"))
        greeting_b, _ = client.answer_to(b, "h-b")
        client.send(a, wire.body("status", "s-a"))
        status_a, _ = client.answer_to(a, "s-a")

    assert greeting_b["role"] == "reader" and status_a["type"] == "status.result"


def test_a_second_server_refuses_a_socket_that_is_being_served(
    tmp_path: Path,
) -> None:
    """Given a running server, When another starts on the same socket path,
    Then it raises DaemonAlreadyRunning and the first keeps serving."""
    path = _socket(tmp_path)
    with running(build_server(path)):
        with pytest.raises(DaemonAlreadyRunning), running(build_server(path)):
            pass
        with client.connect(path) as conn:
            client.send(conn, wire.hello())
            greeting, _ = client.answer_to(conn, "h-1")

    assert greeting["type"] == "hello.result"


def test_a_stale_socket_file_is_replaced(tmp_path: Path) -> None:
    """Given a socket file left by a daemon that died, When a server starts,
    Then it binds the path and serves."""
    path = _socket(tmp_path)
    path.parent.mkdir(parents=True, mode=0o700)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as dead:
        dead.bind(str(path))

    with running(build_server(path)), client.connect(path) as conn:
        client.send(conn, wire.hello())
        greeting, _ = client.answer_to(conn, "h-1")

    assert greeting["type"] == "hello.result"


def test_a_path_that_is_not_a_socket_is_never_removed(tmp_path: Path) -> None:
    """Given a regular file where the socket should be, When a server starts,
    Then it refuses (DaemonAlreadyRunning names the path) and the file stays."""
    path = _socket(tmp_path)
    path.parent.mkdir(parents=True, mode=0o700)
    path.write_text("not a socket")

    with pytest.raises(DaemonAlreadyRunning), running(build_server(path)):
        pass

    assert path.read_text() == "not a socket"


def test_a_socket_path_the_os_cannot_bind_is_refused_by_name(tmp_path: Path) -> None:
    """Given a socket path longer than a unix socket address may be, When the
    server starts, Then SocketUnavailable names the path (no bare OSError)."""
    path = tmp_path / ("d" * 120) / "daemon.sock"

    with (
        pytest.raises(SocketUnavailable, match="daemon.sock"),
        running(build_server(path)),
    ):
        pass


# --- Model calls off the event loop (a slow completion stalls nothing) ---

GATE_TIMEOUT_S = 5.0
"""How long a gated model call waits before failing (a hang becomes a failure)."""


class _Gate:
    """A model call in progress: ``entered`` once it started, then it waits
    for ``release`` (bounded, so a broken test fails instead of hanging)."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def hold(self) -> None:
        self.entered.set()
        assert self.release.wait(GATE_TIMEOUT_S), (
            "the gated model call was never released"
        )


class _GatedEmbedding:
    """``HashingEmbedding`` whose every call waits at the gate."""

    def __init__(self, gate: _Gate) -> None:
        self._gate = gate
        self._inner = HashingEmbedding()

    def model(self) -> ModelInfo:
        return self._inner.model()

    def embed(self, text: str) -> Embedding:
        self._gate.hold()
        return self._inner.embed(text)


class _GatedCompletion(ScriptedCompletion):
    """A completion whose diff proposal waits at the gate, then proposes none."""

    def __init__(self, gate: _Gate) -> None:
        super().__init__(answer=[DraftAnswer(text="Slowly.", cited=(), urls=())])
        self._gate = gate

    def propose_diff(
        self, kind: DiffKind, *, outline: TreeOutline, own_bar: TreeOutline
    ) -> tuple[DiffProposal, ...]:
        self._gate.hold()
        return ()


def _model_request(kind: str, request_id: str) -> bytes:
    if kind == "ask":
        return wire.body(kind, request_id, question="how?", history=[])
    if kind == "search":
        return wire.body(kind, request_id, query="tokio")
    return wire.body(kind, request_id, kind="audit")


@pytest.mark.parametrize("kind", ["ask", "search", "diff.propose"])
def test_a_slow_model_call_does_not_stall_other_connections_or_later_requests(
    tmp_path: Path, kind: str
) -> None:
    """Given a model-backed request whose model call is still running, When
    another profile's connection and the same connection send requests, Then
    both are answered before it returns, and it is answered by its id once
    the model does (contract v1: responses may arrive in any order)."""
    path = _socket(tmp_path)
    gate = _Gate()
    server = build_server(
        path, embedding=_GatedEmbedding(gate), completion=_GatedCompletion(gate)
    )
    with running(server), client.connect(path) as slow, client.connect(path) as other:
        client.send(slow, wire.hello())
        client.answer_to(slow, "h-1")
        client.send(slow, wire.tree_snapshot("t-1"))
        client.answer_to(slow, "t-1")
        client.send(other, wire.hello("h-2", profile="profile-b"))
        client.answer_to(other, "h-2")

        client.send(slow, _model_request(kind, "m-1"))
        assert gate.entered.wait(GATE_TIMEOUT_S), f"{kind} never reached its model"
        client.send(other, wire.body("status", "s-2"))
        other_status, _ = client.answer_to(other, "s-2")
        client.send(slow, wire.body("status", "s-1"))
        same_status, _ = client.answer_to(slow, "s-1")
        gate.release.set()
        answer, _ = client.answer_to(slow, "m-1")

    assert (other_status["type"], same_status["type"]) == (
        "status.result",
        "status.result",
    )
    assert answer["type"] == f"{kind}.result"
