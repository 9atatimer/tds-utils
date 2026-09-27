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

from dynomark_daemon.settings import socket_path

CHUNK: Final = 65536
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


def pipe(stdin_fd: int, stdout_fd: int, daemon: socket.socket) -> None:
    """Copy stdin -> daemon and daemon -> stdout until either side closes."""
    with selectors.DefaultSelector() as selector:
        selector.register(stdin_fd, selectors.EVENT_READ, "browser")
        selector.register(daemon, selectors.EVENT_READ, "daemon")
        while True:
            for key, _ in selector.select():
                if key.data == "browser":
                    data = os.read(stdin_fd, CHUNK)
                    if not data:
                        return
                    daemon.sendall(data)
                else:
                    data = daemon.recv(CHUNK)
                    if not data:
                        return
                    _write_all(stdout_fd, data)


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


def main() -> None:
    """``dynomark-host [origin]``: the browser passes the calling origin."""
    sys.exit(run_host(socket_path(os.environ, home=Path.home())))


if __name__ == "__main__":
    main()
