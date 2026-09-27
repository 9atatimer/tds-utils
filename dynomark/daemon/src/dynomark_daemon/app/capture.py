"""Use case: content is captured, daemon side (DYNOMARK.DESIGN.md, The daemon,
"Capture fallback").

Runs only when the ingest's capture has source ``none``; the fetch adapter
carries no cookies. A page that cannot be read leaves source ``none`` and
the job continues.
"""

from dynomark_daemon.domain.bookmark import Bookmark, Capture, is_fetchable
from dynomark_daemon.ports.content import ContentSourcePort, ContentUnavailable


def capture(bookmark: Bookmark, *, content: ContentSourcePort) -> Capture:
    """Read ``bookmark``'s page through ``content``; ``none`` when it cannot."""
    if not is_fetchable(bookmark.url):
        return Capture.none()
    try:
        return content.read(bookmark)
    except ContentUnavailable:
        return Capture.none()
