"""``dynomark-host``: the native-messaging host ``tds.dynomark``.

The browser starts it with the extension's origin as an argument and talks
contract v1 frames on its stdio. It connects to the daemon's socket and
copies bytes both ways unchanged, never parsing them (contract/v1 README,
Framing), until either side closes. When no daemon answers, it reads the
first frame and answers it with one ``error`` ``busy`` (retry later), so
the extension never waits on a pipe to nothing.
"""

import json
import os
import selectors
import socket
import sys
from pathlib import Path
from typing import Final

from dynomark_daemon.settings import ConfigError, load_settings, socket_path

CHUNK: Final = 65536
UPSTREAM_HIGH_WATER: Final = 1 << 20
"""Browser bytes held for the daemon before the host stops reading stdin."""
HEADER: Final = 4
NO_DAEMON: Final = "the dynomark daemon is not running"


# --- Helpers ---


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        view = view[written:]


def _read_exactly(fd: int, size: int) -> bytes | None:
    data = b""
    while len(data) < size:
        chunk = os.read(fd, size - len(data))
        if not chunk:
            return None
        data += chunk
    return data


def _request_id(body: bytes) -> str | None:
    """The first frame's ``id`` if it reads as one; ``None`` otherwise."""
    try:
        document = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    candidate = document.get("id") if isinstance(document, dict) else None
    return candidate if isinstance(candidate, str) and candidate else None


def _busy_frame(re: str | None) -> bytes:
    body = json.dumps(
        {"v": 1, "type": "error", "re": re, "code": "busy", "message": NO_DAEMON},
        separators=(",", ":"),
    ).encode("utf-8")
    return len(body).to_bytes(HEADER, "little") + body


# --- Flows ---


def _interest(upstream: bytearray) -> int:
    """What to wait for on the daemon socket: always its answers, and room to
    write while browser bytes wait to go up."""
    return selectors.EVENT_READ | (selectors.EVENT_WRITE if upstream else 0)


def pipe(stdin_fd: int, stdout_fd: int, daemon: socket.socket) -> None:
    """Copy stdin -> daemon and daemon -> stdout until either side closes.

    The daemon is never left unread: it drains each answer before it reads
    the next frame, so a host blocked writing a large browser frame to it
    while it waits to write a large answer would stall both for good.
    Browser bytes wait in a buffer (at most ``UPSTREAM_HIGH_WATER``; stdin
    is not read past it) and go up as the socket takes them; the daemon's
    bytes go to stdout as they come. Once the browser closes, what it sent
    is still delivered before the pipe returns.
    """
    daemon.setblocking(False)
    upstream = bytearray()
    browser_open = True
    with selectors.DefaultSelector() as selector:
        selector.register(daemon, _interest(upstream), "daemon")
        while browser_open or upstream:
            reading = browser_open and len(upstream) < UPSTREAM_HIGH_WATER
            if reading and stdin_fd not in selector.get_map():
                selector.register(stdin_fd, selectors.EVENT_READ, "browser")
            elif not reading and stdin_fd in selector.get_map():
                selector.unregister(stdin_fd)
            selector.modify(daemon, _interest(upstream), "daemon")
            for key, events in selector.select():
                if key.data == "browser":
                    data = os.read(stdin_fd, CHUNK)
                    if data:
                        upstream += data
                    else:
                        browser_open = False
                    continue
                if events & selectors.EVENT_READ:
                    try:
                        answer = daemon.recv(CHUNK)
                    except BlockingIOError:
                        answer = None
                    if answer == b"":
                        return
                    if answer:
                        _write_all(stdout_fd, answer)
                if events & selectors.EVENT_WRITE and upstream:
                    try:
                        sent = daemon.send(upstream)
                    except BlockingIOError:
                        sent = 0
                    del upstream[:sent]


def answer_unavailable(stdin_fd: int, stdout_fd: int) -> None:
    """Answer the browser's first frame with ``error`` ``busy``."""
    header = _read_exactly(stdin_fd, HEADER)
    if header is None:
        return
    body = _read_exactly(stdin_fd, int.from_bytes(header, "little")) or b""
    _write_all(stdout_fd, _busy_frame(_request_id(body)))


def run_host(path: Path, *, stdin_fd: int = 0, stdout_fd: int = 1) -> int:
    """Pipe the browser to the daemon at ``path``; 0 when either side closed."""
    daemon = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        daemon.connect(str(path))
    except OSError:
        daemon.close()
        answer_unavailable(stdin_fd, stdout_fd)
        return 0
    try:
        pipe(stdin_fd, stdout_fd, daemon)
    except (BrokenPipeError, ConnectionError):
        return 0
    finally:
        daemon.close()
    return 0


# --- Entry point ---


def daemon_socket() -> Path:
    """The socket the daemon listens on: its config's, or the default when the
    config cannot be read (the daemon then refuses to start anyway)."""
    home = Path.home()
    try:
        return load_settings(os.environ, home=home, hostname="").socket_path
    except ConfigError:
        return socket_path(os.environ, home=home)


def main() -> None:
    """``dynomark-host [origin]``: the browser passes the calling origin."""
    sys.exit(run_host(daemon_socket()))


if __name__ == "__main__":
    main()
