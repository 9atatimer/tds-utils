"""``ContentSourcePort`` by fetch: the daemon's capture fallback.

DYNOMARK.DESIGN.md, The daemon, "Capture fallback": used only when the
ingest's capture is ``none``; carries no cookies; skips non-http(s) URLs
(Security Considerations, "Daemon-side fetch"). urllib with an opener
built from the handlers it needs and nothing else: no cookie processor, no
proxies, no file/ftp/data handlers, redirects followed only to http(s) and
at most ``MAX_REDIRECTS`` times. At most ``max_bytes`` of the body are
read; readable text comes from ``readable.py``.
"""

import re
import ssl
import urllib.error
import urllib.request
from email.message import Message
from http.client import HTTPMessage
from typing import IO, Final
from urllib.parse import urlsplit

from dynomark_daemon.adapters.readable import readable
from dynomark_daemon.domain.bookmark import Bookmark, Capture, CaptureSource
from dynomark_daemon.ports.content import ContentUnavailable

SCHEMES: Final = frozenset({"http", "https"})
TEXT_TYPES: Final = frozenset({"text/html", "application/xhtml+xml", "text/plain"})
MAX_REDIRECTS: Final = 5
USER_AGENT: Final = "dynomark/0.1 (local bookmark capture; no cookies)"
META_CHARSET: Final = re.compile(rb"""<meta[^>]+charset=["']?([A-Za-z0-9._-]+)""", re.I)
SNIFF_BYTES: Final = 4096


# --- Helpers ---


class _HttpOnlyRedirects(urllib.request.HTTPRedirectHandler):
    max_redirections = MAX_REDIRECTS

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        if urlsplit(newurl).scheme.lower() not in SCHEMES:
            raise urllib.error.HTTPError(
                newurl, code, "redirect off http(s) refused", headers, fp
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener() -> urllib.request.OpenerDirector:
    opener = urllib.request.OpenerDirector()
    for handler in (
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPHandler(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        _HttpOnlyRedirects(),
        urllib.request.HTTPDefaultErrorHandler(),
        urllib.request.HTTPErrorProcessor(),
    ):
        opener.add_handler(handler)
    return opener


def _charset(headers: Message, head: bytes) -> str:
    declared = headers.get_content_charset()
    if declared:
        return declared
    sniffed = META_CHARSET.search(head[:SNIFF_BYTES])
    return sniffed.group(1).decode("ascii") if sniffed else "utf-8"


def _decode(raw: bytes, charset: str) -> str:
    try:
        return raw.decode(charset, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def _unavailable(url: str, why: str, *, retryable: bool) -> ContentUnavailable:
    return ContentUnavailable(f"cannot fetch {url}: {why}", retryable=retryable)


# --- The adapter ---


class FetchContentSource:
    def __init__(
        self, *, timeout_s: float, max_bytes: int, user_agent: str = USER_AGENT
    ) -> None:
        self._timeout_s = timeout_s
        self._max_bytes = max_bytes
        self._user_agent = user_agent
        self._opener = _opener()

    def read(self, bookmark: Bookmark) -> Capture:
        """The page's readable text, ``source`` ``fetch``.

        Raises:
            ContentUnavailable: not http(s), an HTTP error, a timeout, a
                non-text page, or no readable text.
        """
        url = bookmark.url
        if urlsplit(url).scheme.lower() not in SCHEMES:
            raise _unavailable(url, "only http(s) is fetched", retryable=False)
        request = urllib.request.Request(
            url, headers={"User-Agent": self._user_agent, "Accept": "text/html"}
        )
        try:
            with self._opener.open(request, timeout=self._timeout_s) as response:
                headers: Message = response.headers
                content_type = headers.get_content_type()
                if content_type not in TEXT_TYPES:
                    raise _unavailable(url, content_type, retryable=False)
                raw = response.read(self._max_bytes)
        except urllib.error.HTTPError as error:
            raise _unavailable(url, str(error), retryable=error.code >= 500) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise _unavailable(url, str(error), retryable=True) from error
        text = _decode(raw, _charset(headers, raw))
        if content_type == "text/plain":
            return Capture(source=CaptureSource.FETCH, text=text.strip())
        page = readable(text)
        if not page.text:
            raise _unavailable(url, "no readable text", retryable=False)
        return Capture(source=CaptureSource.FETCH, text=page.text, title=page.title)
