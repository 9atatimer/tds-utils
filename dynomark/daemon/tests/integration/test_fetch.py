"""The daemon's fetch ContentSourcePort (DYNOMARK.DESIGN.md, The daemon,
"Capture fallback ... carries no cookies; skips non-http(s) URLs";
Security Considerations, "Daemon-side fetch"). A local ``http.server`` on
127.0.0.1 only; no network.
"""

import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

import pytest

from dynomark_daemon.adapters.fetch import FetchContentSource
from dynomark_daemon.domain.bookmark import CaptureSource
from dynomark_daemon.ports.content import ContentSourcePort, ContentUnavailable
from tests._factories import make_bookmark

pytestmark = pytest.mark.integration

PAGES = Path(__file__).resolve().parents[1] / "fixtures" / "pages"
RELEASE_TIMEOUT_S = 5.0


class _Site(BaseHTTPRequestHandler):
    """Serves the fixture pages and a few scripted routes; records headers."""

    seen: ClassVar[list[dict[str, str]]] = []
    release: ClassVar[threading.Event] = threading.Event()

    def log_message(self, format: str, *args: object) -> None:
        return None

    def _send(self, code: int, body: bytes, content_type: str, **headers: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in headers.items():
            self.send_header(name.replace("_", "-"), value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        type(self).seen.append({k.lower(): v for k, v in self.headers.items()})
        routes = {
            "/set-cookie": lambda: self._send(
                302, b"", "text/html", Location="/article.html", Set_Cookie="s=1"
            ),
            "/to-file": lambda: self._send(
                302, b"", "text/html", Location="file:///etc/passwd"
            ),
            "/missing": lambda: self._send(404, b"no", "text/html"),
            "/down": lambda: self._send(503, b"later", "text/html"),
            "/pdf": lambda: self._send(200, b"%PDF-1.4", "application/pdf"),
            "/plain": lambda: self._send(200, b"just text", "text/plain"),
            "/huge": lambda: self._send(
                200, b"<p>" + b"word " * 400_000 + b"</p>", "text/html"
            ),
            "/latin1": lambda: self._send(
                200,
                (PAGES / "latin1.html").read_bytes(),
                "text/html; charset=iso-8859-1",
            ),
            "/stall": self._stall,
        }
        route = routes.get(self.path)
        if route is not None:
            route()
            return
        page = PAGES / self.path.lstrip("/")
        if page.is_file():
            self._send(200, page.read_bytes(), "text/html; charset=utf-8")
        else:
            self._send(404, b"", "text/html")

    def _stall(self) -> None:
        type(self).release.wait(RELEASE_TIMEOUT_S)


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request: object, client_address: object) -> None:
        """A client that stops reading (the byte cap, the timeout) is expected."""
        return None


@pytest.fixture
def site() -> Iterator[str]:
    _Site.seen = []
    _Site.release = threading.Event()
    server = _Server(("127.0.0.1", 0), _Site)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        _Site.release.set()
        server.shutdown()
        server.server_close()


def _fetch(**overrides: float | int) -> ContentSourcePort:
    settings = {"timeout_s": 2.0, "max_bytes": 5_000_000, **overrides}
    return FetchContentSource(
        timeout_s=float(settings["timeout_s"]), max_bytes=int(settings["max_bytes"])
    )


def test_fetch_captures_the_readable_article_text(site: str) -> None:
    """Given an article page, When read, Then the capture is source fetch with
    the page title and the article text, without navigation or scripts."""
    capture = _fetch().read(make_bookmark(f"{site}/article.html"))

    assert capture.source is CaptureSource.FETCH
    assert capture.title == "Tokio tutorial & guide"
    assert "Cancellation happens at await points." in capture.text
    for chrome in ("Navigation link", "Site header", "footer", "trackingSecret"):
        assert chrome not in capture.text


def test_fetch_sends_no_cookie_even_when_one_is_set(site: str) -> None:
    """Given a site that sets a cookie and redirects, When read, Then the page
    is captured and no request carried a Cookie header."""
    capture = _fetch().read(make_bookmark(f"{site}/set-cookie"))

    assert "asynchronous runtime" in capture.text
    assert len(_Site.seen) == 2
    assert all("cookie" not in headers for headers in _Site.seen)


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "ftp://127.0.0.1/x", "javascript:alert(1)"]
)
def test_fetch_refuses_non_http_urls_without_a_request(url: str, site: str) -> None:
    """Given a non-http(s) url, When read, Then ContentUnavailable and no
    request was made."""
    with pytest.raises(ContentUnavailable):
        _fetch().read(make_bookmark(url))

    assert _Site.seen == []


def test_fetch_refuses_a_redirect_off_http(site: str) -> None:
    """Given an http page redirecting to file://, When read, Then
    ContentUnavailable (the redirect is never followed)."""
    with pytest.raises(ContentUnavailable):
        _fetch().read(make_bookmark(f"{site}/to-file"))


@pytest.mark.parametrize(
    ("path", "retryable"), [("/missing", False), ("/down", True), ("/pdf", False)]
)
def test_fetch_failures_are_content_unavailable(
    site: str, path: str, retryable: bool
) -> None:
    """Given a 404, a 503 or a non-text page, When read, Then ContentUnavailable
    says whether trying again could help."""
    with pytest.raises(ContentUnavailable) as raised:
        _fetch().read(make_bookmark(f"{site}{path}"))

    assert raised.value.retryable is retryable


def test_fetch_times_out_on_a_silent_server(site: str) -> None:
    """Given a server that never answers, When read with a short timeout, Then
    ContentUnavailable (retryable) instead of a hang."""
    with pytest.raises(ContentUnavailable) as raised:
        _fetch(timeout_s=0.2).read(make_bookmark(f"{site}/stall"))

    assert raised.value.retryable is True


def test_fetch_reads_at_most_max_bytes(site: str) -> None:
    """Given a 2 MB page and a 64 KiB cap, When read, Then the capture holds
    only text from the first 64 KiB."""
    capture = _fetch(max_bytes=65_536).read(make_bookmark(f"{site}/huge"))

    assert 0 < len(capture.text) <= 65_536


def test_fetch_decodes_the_declared_charset_and_plain_text(site: str) -> None:
    """Given an iso-8859-1 page and a text/plain page, When read, Then both are
    decoded to the right characters."""
    latin = _fetch().read(make_bookmark(f"{site}/latin1"))
    plain = _fetch().read(make_bookmark(f"{site}/plain"))

    assert (latin.title, latin.text) == ("Café", "crème brûlée")
    assert plain.text == "just text"


@pytest.mark.parametrize(
    ("page", "expected", "absent"),
    [
        ("main.html", "Roses need pruning in late winter.", "Sidebar"),
        ("plain-body.html", "Second paragraph.", "footer words"),
    ],
)
def test_fetch_falls_back_to_main_then_body(
    site: str, page: str, expected: str, absent: str
) -> None:
    """Given pages without an article, When read, Then main, else the body,
    is captured without the page chrome."""
    capture = _fetch().read(make_bookmark(f"{site}/{page}"))

    assert expected in capture.text and absent not in capture.text
