"""A local stand-in for the Ollama HTTP API (127.0.0.1 only) for adapter tests.

Answers ``/api/embed``, ``/api/generate`` and ``/api/tags`` from scripts and
records every request body. ``generate`` answers are the model's raw
``response`` strings, so a test scripts exactly what the model "said".
"""

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

JsonObject = dict[str, object]


@dataclass
class Script:
    embeddings: list[list[float]] = field(default_factory=list)
    responses: list[str] = field(default_factory=list)
    models: list[str] = field(default_factory=list)
    status: int = 200
    requests: list[tuple[str, JsonObject]] = field(default_factory=list)


class _Handler(BaseHTTPRequestHandler):
    script: Script

    def log_message(self, format: str, *args: object) -> None:
        return None

    def _reply(self, code: int, document: JsonObject) -> None:
        body = json.dumps(document).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self.script.requests.append((self.path, {}))
        if self.path == "/api/tags":
            self._reply(200, {"models": [{"name": n} for n in self.script.models]})
        else:
            self._reply(404, {"error": "not found"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        self.script.requests.append((self.path, payload))
        if self.script.status != 200:
            self._reply(
                self.script.status,
                {"error": f"model '{payload.get('model')}' not found"},
            )
        elif self.path == "/api/embed":
            self._reply(200, {"embeddings": [self.script.embeddings.pop(0)]})
        elif self.path == "/api/generate":
            self._reply(200, {"response": self.script.responses.pop(0), "done": True})
        else:
            self._reply(404, {"error": "not found"})


class _Server(ThreadingHTTPServer):
    daemon_threads = True


@contextmanager
def fake_ollama(script: Script) -> Iterator[str]:
    """The base URL of a fake Ollama answering from ``script``."""
    handler = type("Handler", (_Handler,), {"script": script})
    server = _Server(("127.0.0.1", 0), handler)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
