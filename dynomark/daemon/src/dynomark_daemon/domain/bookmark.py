"""A saved bookmark, its capture, and the corpus entry built from them."""

import re
import string
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Self

from dynomark_daemon.domain.ids import NodeId
from dynomark_daemon.domain.tree import FolderPath

# --- Identity normalization (RFC 3986, sections 6.2.2 and 6.2.3) ---

_SCHEME: Final = re.compile(r"([A-Za-z][A-Za-z0-9+.-]*):(.*)", re.DOTALL)
_DEFAULT_PORTS: Final = {"http": 80, "https": 443}
_UNRESERVED: Final = frozenset(string.ascii_letters + string.digits + "-._~")
_ESCAPE: Final = re.compile(r"%([0-9A-Fa-f]{2})")
_STRAY_PERCENT: Final = re.compile(r"%(?![0-9A-Fa-f]{2})")
_PORT: Final = re.compile(r"(:[0-9]*)?")
_ASCII_LOWER: Final = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)


def _has_malformed_escape(text: str) -> bool:
    return _STRAY_PERCENT.search(text) is not None


def _normalize_escapes(text: str) -> str:
    """Upper-case every escape and decode the unreserved ones.

    A component holding a malformed escape is left as it is: decoding
    around a stray ``%`` could create a new escape and change the URL.
    """
    if _has_malformed_escape(text):
        return text

    def _one(match: re.Match[str]) -> str:
        char = chr(int(match.group(1), 16))
        return char if char in _UNRESERVED else "%" + match.group(1).upper()

    return _ESCAPE.sub(_one, text)


def _remove_dot_segments(path: str) -> str:
    """RFC 3986, section 5.2.4."""
    output: list[str] = []
    rest = path
    while rest:
        if rest.startswith("../"):
            rest = rest[3:]
        elif rest.startswith("./"):
            rest = rest[2:]
        elif rest.startswith("/./") or rest == "/.":
            rest = "/" + rest[3:]
        elif rest.startswith("/../") or rest == "/..":
            rest = "/" + rest[4:]
            if output:
                output.pop()
        elif rest in (".", ".."):
            rest = ""
        else:
            cut = rest.find("/", 1)
            cut = len(rest) if cut < 0 else cut
            output.append(rest[:cut])
            rest = rest[cut:]
    return "".join(output)


def _split_off(text: str, marker: str) -> tuple[str, str | None]:
    head, found, tail = text.partition(marker)
    return head, (tail if found else None)


def _normalize_authority(authority: str, scheme: str) -> str | None:
    """Lower-case the host and drop an empty or default port; ``None`` when
    the authority cannot be read (the URL is then left as it is)."""
    userinfo, at, hostport = authority.rpartition("@")
    if hostport.startswith("["):
        close = hostport.find("]")
        if close < 0:
            return None
        host, port_part = hostport[: close + 1], hostport[close + 1 :]
    else:
        host, colon, port = hostport.partition(":")
        port_part = colon + port
    if _PORT.fullmatch(port_part) is None:
        return None
    port = port_part[1:]
    keep_port = port != "" and int(port) != _DEFAULT_PORTS[scheme]
    return f"{userinfo}{at}{host.translate(_ASCII_LOWER)}" + (
        f":{port}" if keep_port else ""
    )


def normalize_url(url: str) -> str:
    """The identity spelling of ``url``: equivalent variants removed only.

    For http(s): scheme and host lower-cased, an empty or default port
    dropped, escapes upper-cased and unreserved ones decoded, dot segments
    removed, an empty path made ``/``. Path case, query order, fragments,
    userinfo and encoded reserved characters are kept: each may name
    another resource. Any other scheme is only lower-cased.
    """
    match = _SCHEME.fullmatch(url)
    if match is None:
        return url
    scheme, rest = match.group(1).lower(), match.group(2)
    if scheme not in _DEFAULT_PORTS or not rest.startswith("//"):
        return f"{scheme}:{rest}"
    rest, fragment = _split_off(rest[2:], "#")
    rest, query = _split_off(rest, "?")
    cut = rest.find("/")
    authority, path = (rest, "") if cut < 0 else (rest[:cut], rest[cut:])
    normalized_authority = _normalize_authority(authority, scheme)
    if normalized_authority is None:
        return f"{scheme}:{match.group(2)}"
    path = _remove_dot_segments(_normalize_escapes(path)) or "/"
    identity = f"{scheme}://{normalized_authority}{path}"
    if query is not None:
        identity += "?" + _normalize_escapes(query)
    if fragment is not None:
        identity += "#" + _normalize_escapes(fragment)
    return identity


def is_fetchable(url: str) -> bool:
    """Only http(s) pages are ever captured (Security Considerations)."""
    match = _SCHEME.fullmatch(url)
    return match is not None and match.group(1).lower() in _DEFAULT_PORTS


@dataclass(frozen=True, slots=True)
class Identity:
    """The normalized URL: the cross-host identity of a bookmark.

    Computed on the daemon only; the extension sends the raw URL.
    """

    value: str

    @classmethod
    def from_url(cls, url: str) -> Self:
        """The identity of a raw URL as the browser reported it."""
        return cls(normalize_url(url))


@dataclass(frozen=True, slots=True)
class Bookmark:
    """A raw URL plus title at a ``FolderPath``, with its per-profile ``NodeId``."""

    node_id: NodeId
    url: str
    title: str
    path: FolderPath
    date_added: int


class CaptureSource(StrEnum):
    TAB = "tab"
    BACKGROUND_TAB = "background_tab"
    FETCH = "fetch"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class Capture:
    """Readable text plus title for a bookmark, and where it came from."""

    source: CaptureSource
    text: str
    title: str | None = None

    @classmethod
    def none(cls) -> Self:
        """No content: nothing could be read."""
        return cls(source=CaptureSource.NONE, text="")


@dataclass(frozen=True, slots=True)
class Save:
    """What one ingest brings: the bookmark as saved and its capture."""

    bookmark: Bookmark
    capture: Capture


@dataclass(frozen=True, slots=True)
class Embedding:
    """A vector plus the id of the model that produced it."""

    vector: tuple[float, ...]
    model_id: str


@dataclass(frozen=True, slots=True)
class Enrichment:
    """What the completion model returns for a capture: summary and tags."""

    summary: str
    tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CorpusEntry:
    """A bookmark plus capture, summary, tags and embedding."""

    identity: Identity
    bookmark: Bookmark
    capture: Capture
    summary: str
    tags: tuple[str, ...]
    embedding: Embedding
    indexed_at: int
