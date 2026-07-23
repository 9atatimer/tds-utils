"""Unit tests for the claude-cli classifier adapter (injected runner)."""

from __future__ import annotations

import json

import pytest

from orgmarks.adapters.claude_cli import ClaudeCliClassifier
from orgmarks.domain.errors import InfrastructureError
from orgmarks.domain.model import Bookmark, FolderPath


def _bm(url: str) -> Bookmark:
    return Bookmark(
        url=url, title="t", add_date=1, source_path=FolderPath.from_string("other")
    )


def _good_response(url: str) -> str:
    return json.dumps(
        [
            {
                "url": url,
                "folder": "work/dev",
                "ref": "technical/dev",
                "confidence": 0.9,
                "proposed_new_folder": "work/newarea",
            }
        ]
    )


def test_happy_path_parses_results() -> None:
    """Given valid JSON, When classified, Then a ClassifyResult is returned."""
    url = "https://example.com/a"
    clf = ClaudeCliClassifier(runner=lambda _prompt: _good_response(url))
    out = clf.classify([_bm(url)], intents=(), skeleton="")
    assert out[0].folder == FolderPath.from_string("work/dev")
    assert out[0].confidence == 0.9
    assert out[0].proposed_new_folder == "work/newarea"


def test_response_wrapped_in_prose_is_tolerated() -> None:
    """Given JSON amid prose, When classified, Then it is still parsed."""
    url = "https://example.com/a"
    noisy = f"Sure! Here is the result:\n{_good_response(url)}\nHope that helps."
    clf = ClaudeCliClassifier(runner=lambda _p: noisy)
    out = clf.classify([_bm(url)], intents=(), skeleton="")
    assert out[0].folder == FolderPath.from_string("work/dev")


def test_malformed_then_valid_is_retried_once() -> None:
    """Given one bad then one good response, When classified, Then retry wins."""
    url = "https://example.com/a"
    responses = iter(["not json at all", _good_response(url)])

    def runner(_prompt: str) -> str:
        return next(responses)

    clf = ClaudeCliClassifier(runner=runner)
    out = clf.classify([_bm(url)], intents=(), skeleton="")
    assert out[0].confidence == 0.9


def test_malformed_twice_falls_back_to_triage() -> None:
    """Given two bad responses, When classified, Then results are low-confidence."""
    clf = ClaudeCliClassifier(runner=lambda _p: "still not json")
    out = clf.classify([_bm("https://example.com/a")], intents=(), skeleton="")
    assert out[0].confidence == 0.0


def test_missing_binary_raises_infrastructure_error() -> None:
    """Given a runner that raises, When classified, Then it surfaces as infra."""

    def runner(_prompt: str) -> str:
        raise InfrastructureError("claude CLI not found on PATH")

    clf = ClaudeCliClassifier(runner=runner)
    with pytest.raises(InfrastructureError):
        clf.classify([_bm("https://example.com/a")], intents=(), skeleton="")
