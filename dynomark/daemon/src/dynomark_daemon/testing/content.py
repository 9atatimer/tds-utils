"""A fetch ``ContentSourcePort`` over scripted pages; no network."""

from collections.abc import Mapping

from dynomark_daemon.domain.bookmark import Bookmark, Capture, CaptureSource
from dynomark_daemon.ports.content import ContentUnavailable


class FakeFetch:
    """Reads ``pages[url] = (title, text)``; any other url is unavailable. A
    url in ``outages`` first fails that many reads with a retryable error (a
    5xx or a timeout), then reads as ``pages`` says."""

    def __init__(
        self,
        pages: Mapping[str, tuple[str, str]],
        *,
        outages: Mapping[str, int] | None = None,
    ) -> None:
        self._pages = dict(pages)
        self._outages = dict(outages or {})
        self.requested: list[str] = []

    def read(self, bookmark: Bookmark) -> Capture:
        self.requested.append(bookmark.url)
        if self._outages.get(bookmark.url, 0) > 0:
            self._outages[bookmark.url] -= 1
            raise ContentUnavailable(
                f"cannot fetch {bookmark.url}: 503", retryable=True
            )
        page = self._pages.get(bookmark.url)
        if page is None:
            raise ContentUnavailable(f"cannot fetch {bookmark.url}", retryable=False)
        title, text = page
        return Capture(source=CaptureSource.FETCH, text=text, title=title)
