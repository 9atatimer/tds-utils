"""A stand-in SystemOne server for the decide client, on the loopback only.

The real `bin/decide` is run against it (DECIDE_BACKEND=systemone), so the
adapter's records go through decide's own validation and its answers
through decide's own normalization; only the model behind the server is
stood in for. It answers every question with an even spread, or each
yes/no with a bare label (no probability), or with one HTTP status, as the
test sets `mode`; it keeps every request body it was sent.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

EVEN = "even"
LABEL = "label"


@dataclass
class StubServer:
    """What the test sets and reads: the answer mode (`even`, `label`, or an
    HTTP status as text), and every request body received."""

    url: str = ""
    mode: str = EVEN
    received: list[dict[str, object]] = field(default_factory=list)


def _answer(question: dict[str, object], mode: str) -> object:
    kind = question.get("type")
    criteria = question.get("criteria")
    if kind == "choice" and isinstance(criteria, dict):
        return {"probabilities": {o: 1.0 / len(criteria) for o in criteria}}
    if kind == "score" and isinstance(criteria, list):
        return {"probabilities": [1.0 / len(criteria)] * len(criteria)}
    return True if mode == LABEL else {"noul": 0.5}


class _Handler(BaseHTTPRequestHandler):
    """Answers POSTs as the StubServer its HTTP server carries says to."""

    def do_POST(self) -> None:  # noqa: N802 -- http.server's name
        server: StubServer = self.server.stub  # type: ignore[attr-defined]
        length = int(self.headers.get("content-length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        server.received.append(body)
        if server.mode.isdigit():
            self._send(int(server.mode), {"error": "stood-in failure"})
            return
        questions = body.get("questions", {})
        answers = {qid: _answer(q, server.mode) for qid, q in questions.items()}
        self._send(200, {"model": body.get("model"), "answers": answers})

    def _send(self, status: int, payload: dict[str, object]) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


@contextmanager
def stub_server() -> Iterator[StubServer]:
    """A running stub on an ephemeral loopback port, shut down on exit."""
    state = StubServer()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.stub = state  # type: ignore[attr-defined]
    state.url = f"http://127.0.0.1:{httpd.server_address[1]}"
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
