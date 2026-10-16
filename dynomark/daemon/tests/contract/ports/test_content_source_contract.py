"""The daemon's ContentSourcePort fake: a fetch that reads scripted pages.

Design: Behaviors "Content falls back to fetch": "Given a request whose
capture has source none, When captured, Then source is fetch; if the fetch
fails, source stays none and the job continues". The fake gives the fetch
result and the fetch failure.
"""

import pytest

from dynomark_daemon.domain.bookmark import CaptureSource
from dynomark_daemon.ports.content import ContentSourcePort, ContentUnavailable
from dynomark_daemon.testing.content import FakeFetch
from tests._factories import make_bookmark

pytestmark = pytest.mark.contract

TOKIO = "https://tokio.rs/tokio/tutorial"


def test_read_known_page_is_a_fetch_capture_of_its_text() -> None:
    """Given a page the fake can fetch, When read, Then the capture's source is
    fetch and its text and title are the page's."""
    port: ContentSourcePort = FakeFetch(
        {TOKIO: ("Tokio tutorial", "Tokio is a runtime")}
    )

    capture = port.read(make_bookmark(TOKIO))

    assert (capture.source, capture.title, capture.text) == (
        CaptureSource.FETCH,
        "Tokio tutorial",
        "Tokio is a runtime",
    )


def test_read_unknown_page_raises_content_unavailable_and_is_recorded() -> None:
    """Given a page the fake cannot fetch, When read, Then ContentUnavailable is
    raised (not retryable) and the attempt is recorded."""
    fake = FakeFetch({})

    with pytest.raises(ContentUnavailable) as raised:
        fake.read(make_bookmark("https://gone.example/"))

    assert raised.value.retryable is False
    assert fake.requested == ["https://gone.example/"]


def test_read_during_an_outage_raises_retryable_then_reads_the_page() -> None:
    """Given a page in an outage of one read, When read twice, Then the first
    read raises a retryable ContentUnavailable and the second reads it."""
    fake = FakeFetch({TOKIO: ("Tokio", "text")}, outages={TOKIO: 1})

    with pytest.raises(ContentUnavailable) as raised:
        fake.read(make_bookmark(TOKIO))
    capture = fake.read(make_bookmark(TOKIO))

    assert raised.value.retryable is True
    assert capture.source is CaptureSource.FETCH
