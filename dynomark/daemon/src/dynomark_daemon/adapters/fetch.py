"""``ContentSourcePort`` by fetch: the daemon's capture fallback.

DYNOMARK.DESIGN.md, The daemon, "Capture fallback": used only when the
ingest's capture is ``none``; carries no cookies; skips non-http(s) URLs
(Security Considerations, "Daemon-side fetch"). urllib with an opener
built from the handlers it needs and nothing else: no cookie processor, no
proxies, no file/ftp/data handlers, redirects followed only to http(s) and
at most ``MAX_REDIRECTS`` times. Every connection, a redirect's included,
goes only to an address the policy allows -- by default a public one, never
loopback, link-local or private -- and to exactly the address it vetted.
At most ``max_bytes`` of the body are read, and the fetch gives up once
``timeout_s`` has passed since it began (one more read may still take up
to ``timeout_s``); readable text comes from ``readable.py``.
"""

import http.client
import re
import socket
import ssl
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from email.message import Message
from http.client import HTTPMessage
from ipaddress import IPv4Address, IPv6Address, ip_address
from typing import IO, Final, Protocol
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
READ_CHUNK: Final = 65536


IPAddress = IPv4Address | IPv6Address
AddressPolicy = Callable[[IPAddress], bool]
"""Whether the fetch may connect to an address (every one a host resolves to
must pass)."""


# --- The address policy ---


def is_public(address: IPAddress) -> bool:
    """A globally routable unicast address: never loopback, link-local,
    private, unspecified, reserved or multicast (an IPv4-mapped IPv6 address
    is judged as its IPv4 address)."""
    if isinstance(address, IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_global and not address.is_multicast


_Connect = Callable[
    [tuple[str, int], float | None, tuple[str, int] | None], socket.socket
]
DEFAULT_TIMEOUT_S: Final = 15.0
"""Only a default of the connection factory's signature: urllib always
passes the request's timeout."""
BLOCKSIZE: Final = 8192


def any_address(address: IPAddress) -> bool:
    """Every address: an install that fetches its intranet and localhost
    pages (``[capture] private_addresses``)."""
    return True


class RefusedAddress(OSError):
    """The host resolves to an address the policy refuses; nothing was sent."""


def _vetted(host: str, port: int, allowed: AddressPolicy) -> str:
    """The address to connect to for ``host``: the first it resolves to, once
    every one of them passed ``allowed``.

    Raises:
        RefusedAddress: some address ``host`` resolves to is refused.
    """
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses = [ip_address(str(info[4][0]).split("%")[0]) for info in infos]
    refused = [a for a in addresses if not allowed(a)]
    if refused or not addresses:
        where = refused[0] if refused else "nothing"
        raise RefusedAddress(f"{host} resolves to {where}, which is not fetched")
    return str(addresses[0])


def _pinned(allowed: AddressPolicy) -> _Connect:
    """A ``create_connection`` that connects only to an address ``allowed``
    passes, and to exactly the one it vetted (a second lookup could answer
    differently)."""

    def connect(
        address: tuple[str, int],
        timeout: float | None = None,
        source_address: tuple[str, int] | None = None,
    ) -> socket.socket:
        host, port = address
        vetted = _vetted(host, port, allowed)
        return socket.create_connection((vetted, port), timeout, source_address)

    return connect


class _VettedHandler(urllib.request.HTTPHandler, urllib.request.HTTPSHandler):
    """http and https whose every connection goes through ``_pinned``; over
    TLS the certificate is still checked against the host name."""

    def __init__(self, allowed: AddressPolicy, context: ssl.SSLContext) -> None:
        urllib.request.HTTPHandler.__init__(self)
        urllib.request.HTTPSHandler.__init__(self, context=context)
        self._connect = _pinned(allowed)
        self._tls = context

    def http_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(self._plain, req)

    def https_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(self._secure, req)

    def _plain(
        self,
        host: str,
        /,
        *,
        port: int | None = None,
        timeout: float = DEFAULT_TIMEOUT_S,
        source_address: tuple[str, int] | None = None,
        blocksize: int = BLOCKSIZE,
    ) -> http.client.HTTPConnection:
        connection = http.client.HTTPConnection(
            host, port, timeout, source_address, blocksize=blocksize
        )
        # http.client's own hook for opening the socket; typeshed omits it.
        connection._create_connection = self._connect  # type: ignore[attr-defined]
        return connection

    def _secure(
        self,
        host: str,
        /,
        *,
        port: int | None = None,
        timeout: float = DEFAULT_TIMEOUT_S,
        source_address: tuple[str, int] | None = None,
        blocksize: int = BLOCKSIZE,
    ) -> http.client.HTTPConnection:
        connection = http.client.HTTPSConnection(
            host,
            port,
            timeout=timeout,
            source_address=source_address,
            context=self._tls,
            blocksize=blocksize,
        )
        # http.client's own hook for opening the socket; typeshed omits it.
        connection._create_connection = self._connect  # type: ignore[attr-defined]
        return connection


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


def _opener(allowed: AddressPolicy) -> urllib.request.OpenerDirector:
    opener = urllib.request.OpenerDirector()
    for handler in (
        urllib.request.ProxyHandler({}),
        _VettedHandler(allowed, ssl.create_default_context()),
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


class _Body(Protocol):
    def read1(self, size: int = ..., /) -> bytes: ...


def _read_body(body: _Body, url: str, *, max_bytes: int, deadline: float) -> bytes:
    """At most ``max_bytes`` of ``body``, read as it arrives; a page still
    arriving at ``deadline`` is given up on (a trickle never times out a
    single read)."""
    raw = bytearray()
    while len(raw) < max_bytes:
        if time.monotonic() >= deadline:
            raise _unavailable(url, "the page took too long to arrive", retryable=True)
        chunk = body.read1(min(READ_CHUNK, max_bytes - len(raw)))
        if not chunk:
            break
        raw += chunk
    return bytes(raw)


# --- The adapter ---


class FetchContentSource:
    def __init__(
        self,
        *,
        timeout_s: float,
        max_bytes: int,
        user_agent: str = USER_AGENT,
        address_allowed: AddressPolicy = is_public,
    ) -> None:
        self._timeout_s = timeout_s
        self._max_bytes = max_bytes
        self._user_agent = user_agent
        self._opener = _opener(address_allowed)

    def read(self, bookmark: Bookmark) -> Capture:
        """The page's readable text, ``source`` ``fetch``.

        Raises:
            ContentUnavailable: not http(s), a url ``http.client`` cannot use,
                an HTTP error, a server breaking HTTP, a timeout, a non-text
                page, or no readable text.
        """
        url = bookmark.url
        deadline = time.monotonic() + self._timeout_s
        try:
            scheme = urlsplit(url).scheme.lower()
        except ValueError as error:
            raise _unavailable(url, str(error), retryable=False) from error
        if scheme not in SCHEMES:
            raise _unavailable(url, "only http(s) is fetched", retryable=False)
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": self._user_agent, "Accept": "text/html"}
            )
            with self._opener.open(request, timeout=self._timeout_s) as response:
                headers: Message = response.headers
                content_type = headers.get_content_type()
                if content_type not in TEXT_TYPES:
                    raise _unavailable(url, content_type, retryable=False)
                raw = _read_body(
                    response, url, max_bytes=self._max_bytes, deadline=deadline
                )
        except urllib.error.HTTPError as error:
            raise _unavailable(url, str(error), retryable=error.code >= 500) from error
        except urllib.error.URLError as error:
            refused = isinstance(error.reason, RefusedAddress)
            raise _unavailable(url, str(error.reason), retryable=not refused) from error
        except (TimeoutError, OSError) as error:
            raise _unavailable(url, str(error), retryable=True) from error
        except http.client.InvalidURL as error:
            raise _unavailable(url, str(error), retryable=False) from error
        except http.client.HTTPException as error:
            # urllib does not wrap these: a garbage status line, a truncated
            # body (IncompleteRead), an over-long header line.
            detail = f"{type(error).__name__}: {error}"
            raise _unavailable(url, detail, retryable=True) from error
        except ValueError as error:
            # A url no request can be made for: an IDNA-refused host label
            # (UnicodeError), a malformed netloc.
            raise _unavailable(url, str(error), retryable=False) from error
        text = _decode(raw, _charset(headers, raw))
        if content_type == "text/plain":
            return Capture(source=CaptureSource.FETCH, text=text.strip())
        page = readable(text)
        if not page.text:
            raise _unavailable(url, "no readable text", retryable=False)
        return Capture(source=CaptureSource.FETCH, text=page.text, title=page.title)
