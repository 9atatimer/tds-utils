"""Unit tests for the plan report formatter."""

from __future__ import annotations

from orgmarks.app.report import format_report
from orgmarks.domain.model import (
    Assignment,
    Bookmark,
    CreateFolder,
    DedupeGroup,
    FolderPath,
    Plan,
    Rule,
    RuleMatch,
)


def _bm(url: str) -> Bookmark:
    return Bookmark(
        url=url, title="t", add_date=1, source_path=FolderPath.from_string("x")
    )


def _move(url: str, via: str) -> Assignment:
    return Assignment(
        bookmark=_bm(url),
        folder=FolderPath.from_string("bookmarks_bar/work"),
        ref=FolderPath.from_string("technical"),
        confidence=1.0,
        via=via,  # type: ignore[arg-type]
    )


def test_report_counts_by_category() -> None:
    """Given moves, When formatted, Then counts and totals appear."""
    plan = Plan(
        moves=(
            _move("https://example.com/a", "rule"),
            _move("https://example.com/b", "triage"),
        ),
        folder_ops=(CreateFolder(path=FolderPath.from_string("bookmarks_bar/work")),),
    )
    text = format_report(plan)
    assert "bookmarks placed: 2" in text
    assert "folders created: 1" in text
    assert "triaged: 1" in text


def test_report_never_truncates_dropped_urls() -> None:
    """Given a long dropped URL, When formatted, Then it appears in full."""
    long_url = "https://example.com/" + "segment/" * 20
    plan = Plan(
        dedupes=(
            DedupeGroup(kept=_bm("https://example.com/a"), dropped=(_bm(long_url),)),
        )
    )
    text = format_report(plan)
    assert long_url in text


def test_report_lists_learned_rules() -> None:
    """Given learned rules, When formatted, Then each is listed."""
    rule = Rule(
        match=RuleMatch(domain="news.example.com"),
        folder=FolderPath.from_string("fun/news"),
        source="learned",
    )
    plan = Plan(learned_rules=(rule,))
    text = format_report(plan)
    assert "learned rules added: 1" in text
    assert "news.example.com -> fun/news" in text
