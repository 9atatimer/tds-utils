"""Behaviors row: Content falls back to fetch (DYNOMARK.DESIGN.md, Behaviors
and Interfaces; The daemon, "Capture fallback") -- the daemon side of
``capture(bookmark, *, content) -> Capture``: "Given a request whose capture
has source none, When captured, Then source is fetch; if the fetch fails,
source stays none"; the fetch "skips non-http(s) URLs".
"""

import pytest

from dynomark_daemon.app.capture import capture
from dynomark_daemon.domain.bookmark import Capture, CaptureSource
from dynomark_daemon.ports.content import ContentUnavailable
from dynomark_daemon.testing.content import FakeFetch
from tests._factories import make_bookmark

URL = "https://tokio.rs/tokio/tutorial"


def test_capture_by_fetch_reads_the_page_with_source_fetch() -> None:
    """Given a page the fetch adapter can read, When captured, Then the capture
    holds its text with source fetch."""
    fetch = FakeFetch({URL: ("Tokio tutorial", "Tokio is an asynchronous runtime")})

    captured = capture(make_bookmark(URL), content=fetch)

    assert captured == Capture(
        source=CaptureSource.FETCH,
        text="Tokio is an asynchronous runtime",
        title="Tokio tutorial",
    )


def test_capture_when_the_fetch_fails_stays_none() -> None:
    """Given a page the fetch adapter cannot read, When captured, Then the
    capture has source none and no text, and nothing is raised (the job
    continues; a non-retryable failure is final)."""
    captured = capture(make_bookmark(URL), content=FakeFetch({}))

    assert captured == Capture(source=CaptureSource.NONE, text="")


def test_capture_of_a_non_http_url_never_fetches() -> None:
    """Given a bookmark whose URL is not http(s), When captured, Then nothing is
    fetched and the capture has source none (Security: daemon-side fetch)."""
    fetch = FakeFetch({"file:///etc/passwd": ("passwd", "root:x:0:0")})

    captured = capture(make_bookmark("file:///etc/passwd"), content=fetch)

    assert captured.source is CaptureSource.NONE
    assert fetch.requested == []


def test_capture_when_the_fetch_fails_retryably_raises_for_a_retry() -> None:
    """Given a page that answers 503, When captured, Then the retryable error
    is raised for the job's RetryPolicy, not turned into source none (issue
    #418)."""
    fetch = FakeFetch({URL: ("Tokio", "text")}, outages={URL: 1})

    with pytest.raises(ContentUnavailable) as raised:
        capture(make_bookmark(URL), content=fetch)

    assert raised.value.retryable is True
