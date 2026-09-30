"""The native-messaging host ``tds.dynomark`` (contract/v1/README.md:
Framing -- "The native-messaging host is a transparent byte pipe: it copies
frames between its stdio and the socket unchanged, in both directions, and
never parses them"; Endpoint -- "The browser starts the shim; the shim
connects to the socket and pipes"). Real pipes, socket pairs and one real
subprocess; hermetic.
"""

import json
import os
import select
import socket
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path

import pytest

from dynomark_daemon.host import pipe, run_host
from tests import _wire as wire
from tests._server import build_server, running

pytestmark = pytest.mark.integration

TIMEOUT_S = 5.0


def _frame(body: bytes) -> bytes:
    return len(body).to_bytes(4, "little") + body


def _read_within(fd: int, size: int) -> bytes:
    """Exactly ``size`` bytes from ``fd``, failing (never hanging) after the
    timeout."""
    data = b""
    while len(data) < size:
        ready, _, _ = select.select([fd], [], [], TIMEOUT_S)
        assert ready, "the host wrote nothing in time"
        chunk = os.read(fd, size - len(data))
        assert chunk, "the host closed stdout early"
        data += chunk
    return data


def _read_all(fd: int) -> bytes:
    chunks = []
    while chunk := os.read(fd, 65536):
        chunks.append(chunk)
    return b"".join(chunks)


def test_pipe_copies_bytes_both_ways_and_ends_when_the_browser_closes() -> None:
    """Given a browser side (stdio) and a daemon side (socket), When the browser
    writes two frames and closes, Then the daemon reads them unchanged, the
    daemon's answer reaches stdout unchanged, and the pipe returns."""
    stdin_read, stdin_write = os.pipe()
    stdout_read, stdout_write = os.pipe()
    host_side, daemon_side = socket.socketpair()
    daemon_side.settimeout(TIMEOUT_S)
    request = _frame(b'{"v":1,"type":"status","id":"s-1"}') * 2
    answer = _frame(b'{"v":1,"type":"status.result","re":"s-1"}')
    os.write(stdin_write, request)
    daemon_side.sendall(answer)
    os.close(stdin_write)

    pipe(stdin_read, stdout_write, host_side)
    os.close(stdout_write)

    received = b""
    while len(received) < len(request):
        received += daemon_side.recv(65536)
    assert received == request
    assert _read_all(stdout_read) == answer


def _pump(target: Callable[[], None]) -> threading.Thread:
    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread


def test_pipe_keeps_reading_the_daemon_while_the_browser_sends_a_large_frame() -> None:
    """Given a daemon that writes a large answer before it reads its next frame
    (it drains each answer first), When the browser sends a large frame right
    behind the request, Then the pipe carries both ways and nothing waits on
    the other: the answer reaches stdout whole, the frame reaches the daemon
    whole, and the pipe ends when both sides are done."""
    stdin_read, stdin_write = os.pipe()
    stdout_read, stdout_write = os.pipe()
    host_side, daemon_side = socket.socketpair()
    answer = _frame(b"a" * 4_000_000)
    request = _frame(b"s" * 4_000_000)
    received = bytearray()
    delivered = bytearray()

    def daemon() -> None:
        daemon_side.sendall(answer)
        while len(received) < len(request):
            chunk = daemon_side.recv(65536)
            if not chunk:
                return
            received.extend(chunk)
        daemon_side.close()

    def browser_writes() -> None:
        view = memoryview(request)
        while view:
            view = view[os.write(stdin_write, view) :]

    def browser_reads() -> None:
        while len(delivered) < len(answer):
            chunk = os.read(stdout_read, 65536)
            if not chunk:
                return
            delivered.extend(chunk)

    threads = [_pump(daemon), _pump(browser_writes), _pump(browser_reads)]
    piping = _pump(lambda: pipe(stdin_read, stdout_write, host_side))
    piping.join(TIMEOUT_S * 2)
    stuck = piping.is_alive()
    if stuck:  # unwedge every blocked side so the suite goes on
        daemon_side.shutdown(socket.SHUT_RDWR)
        host_side.shutdown(socket.SHUT_RDWR)
        os.close(stdin_write)
        os.close(stdout_read)
    for thread in threads:
        thread.join(TIMEOUT_S)
    if not stuck:
        for fd in (stdin_write, stdout_read):
            os.close(fd)
    for fd in (stdin_read, stdout_write):
        os.close(fd)

    assert not stuck, "the host and the daemon wait on each other"
    assert bytes(delivered) == answer
    assert bytes(received) == request


def test_pipe_ends_when_the_daemon_closes() -> None:
    """Given an open browser side, When the daemon closes its end, Then the pipe
    returns (the browser sees the host exit and may reconnect)."""
    stdin_read, stdin_write = os.pipe()
    _, stdout_write = os.pipe()
    host_side, daemon_side = socket.socketpair()
    daemon_side.close()

    pipe(stdin_read, stdout_write, host_side)

    os.close(stdin_write)


def test_without_a_daemon_the_host_answers_busy_instead_of_hanging(
    tmp_path: Path,
) -> None:
    """Given no daemon listening, When the extension's hello arrives, Then the
    host answers one well-formed error frame (code busy, re the hello's id)
    and returns."""
    stdin_read, stdin_write = os.pipe()
    stdout_read, stdout_write = os.pipe()
    os.write(stdin_write, _frame(wire.hello("h-9")))
    os.close(stdin_write)

    code = run_host(
        tmp_path / "absent.sock", stdin_fd=stdin_read, stdout_fd=stdout_write
    )
    os.close(stdout_write)

    out = _read_all(stdout_read)
    body = json.loads(out[4:])
    assert int.from_bytes(out[:4], "little") == len(out) - 4
    assert (body["type"], body["code"], body["re"], body["v"]) == (
        "error",
        "busy",
        "h-9",
        1,
    )
    assert code == 0


def test_without_a_daemon_an_unreadable_first_frame_is_answered_with_re_null(
    tmp_path: Path,
) -> None:
    """Given no daemon and a first frame that is not JSON, When the host
    answers, Then the error's re is null."""
    stdin_read, stdin_write = os.pipe()
    stdout_read, stdout_write = os.pipe()
    os.write(stdin_write, _frame(b"not json"))
    os.close(stdin_write)

    run_host(tmp_path / "absent.sock", stdin_fd=stdin_read, stdout_fd=stdout_write)
    os.close(stdout_write)

    body = json.loads(_read_all(stdout_read)[4:])
    assert (body["code"], body["re"]) == ("busy", None)


def test_the_installed_host_pipes_a_hello_to_the_daemon_and_back(
    tmp_path: Path,
) -> None:
    """Given a daemon listening on $DYNOMARK_SOCKET, When the host runs as its
    own process and the browser sends hello, Then stdout carries the daemon's
    hello.result; when the browser then closes stdin the process exits 0."""
    path = tmp_path / "dynomark" / "daemon.sock"
    env = {**os.environ, "DYNOMARK_SOCKET": str(path)}
    with running(build_server(path)):
        host = subprocess.Popen(
            [sys.executable, "-m", "dynomark_daemon.host", "chrome-extension://x/"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        assert host.stdin is not None and host.stdout is not None
        try:
            host.stdin.write(_frame(wire.hello("h-1")))
            host.stdin.flush()
            out = host.stdout.fileno()
            length = int.from_bytes(_read_within(out, 4), "little")
            answer = json.loads(_read_within(out, length))
            host.stdin.close()
            code = host.wait(timeout=TIMEOUT_S)
        finally:
            host.kill()
            host.wait(timeout=TIMEOUT_S)

    assert (answer["type"], answer["re"]) == ("hello.result", "h-1")
    assert code == 0


def test_the_host_finds_the_socket_the_config_file_names(tmp_path: Path) -> None:
    """Given no $DYNOMARK_SOCKET and a config.toml naming the socket, When the
    host runs, Then it reaches the daemon listening there."""
    path = tmp_path / "custom.sock"
    config = tmp_path / "config" / "dynomark"
    config.mkdir(parents=True)
    (config / "config.toml").write_text(f'[socket]\npath = "{path}"\n')
    env = {k: v for k, v in os.environ.items() if k != "DYNOMARK_SOCKET"}
    env["XDG_CONFIG_HOME"] = str(tmp_path / "config")
    with running(build_server(path)):
        host = subprocess.Popen(
            [sys.executable, "-m", "dynomark_daemon.host"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        assert host.stdin is not None and host.stdout is not None
        try:
            host.stdin.write(_frame(wire.hello("h-2")))
            host.stdin.flush()
            out = host.stdout.fileno()
            length = int.from_bytes(_read_within(out, 4), "little")
            answer = json.loads(_read_within(out, length))
            host.stdin.close()
            host.wait(timeout=TIMEOUT_S)
        finally:
            host.kill()
            host.wait(timeout=TIMEOUT_S)

    assert answer["type"] == "hello.result"
