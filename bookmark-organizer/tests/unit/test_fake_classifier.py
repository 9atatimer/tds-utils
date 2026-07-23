"""Unit tests for the FakeClassifier."""

from __future__ import annotations

from orgmarks.adapters.fake_classifier import FakeClassifier
from orgmarks.domain.model import Bookmark, FolderPath
from orgmarks.ports.classifier import ClassifyResult


def _bm(url: str) -> Bookmark:
    return Bookmark(
        url=url, title="t", add_date=1, source_path=FolderPath.from_string("other")
    )


def test_known_url_maps_as_configured() -> None:
    """Given a table entry, When classified, Then it is returned verbatim."""
    result = ClassifyResult(
        url="https://example.com/a",
        folder=FolderPath.from_string("work/dev"),
        ref=FolderPath.from_string("technical/dev"),
        confidence=0.9,
    )
    fake = FakeClassifier({"https://example.com/a": result})
    out = fake.classify([_bm("https://example.com/a")], intents=(), skeleton="")
    assert out == [result]


def test_unknown_url_falls_back_to_low_confidence() -> None:
    """Given an uncovered url, When classified, Then confidence is low."""
    fake = FakeClassifier()
    out = fake.classify([_bm("https://example.com/x")], intents=(), skeleton="")
    assert out[0].confidence == 0.0
    assert out[0].url == "https://example.com/x"


def test_result_count_matches_batch_size() -> None:
    """Given a batch, When classified, Then one result per bookmark returns."""
    fake = FakeClassifier()
    batch = [_bm(f"https://example.com/{i}") for i in range(5)]
    assert len(fake.classify(batch, intents=(), skeleton="")) == 5
