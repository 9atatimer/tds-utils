"""A fetch ``ContentSourcePort`` over scripted pages; no network."""

from collections.abc import Mapping

from dynomark_daemon.domain.bookmark import Bookmark, Capture, CaptureSource
from dynomark_daemon.ports.content import ContentUnavailable


class FakeFetch:
    """Reads ``pages[url] = (title, text)``; any other url is unavailable."""

    def __init__(self, pages: Mapping[str, tuple[str, str]]) -> None:
        self._pages = dict(pages)
        self.requested: list[str] = []

    def read(self, bookmark: Bookmark) -> Capture:
        self.requested.append(bookmark.url)
        page = self._pages.get(bookmark.url)
        if page is None:
            raise ContentUnavailable(f"cannot fetch {bookmark.url}", retryable=False)
        title, text = page
        return Capture(source=CaptureSource.FETCH, text=text, title=title)
