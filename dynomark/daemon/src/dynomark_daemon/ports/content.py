"""Seam: where page content comes from (daemon side: fetch and extract)."""

from typing import Protocol

from dynomark_daemon.domain.bookmark import Bookmark, Capture
from dynomark_daemon.ports.errors import PortError


class ContentUnavailable(PortError):
    """The page could not be read; the capture stays ``none``."""


class ContentSourcePort(Protocol):
    def read(self, bookmark: Bookmark) -> Capture:
        """Readable text for ``bookmark.url``, with the source that produced it.

        Raises:
            ContentUnavailable: nothing could be read.
        """
        ...
