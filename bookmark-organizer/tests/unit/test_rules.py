"""Unit tests for the rule engine: pins, first-match, stay-put, residue."""

from __future__ import annotations

from orgmarks.domain.model import Bookmark, FolderPath, Rule, RuleMatch
from orgmarks.domain.rules import assign_by_rules
from orgmarks.domain.taxonomy import Intent, Taxonomy


def _bm(url: str, path: str, *, title: str = "t") -> Bookmark:
    return Bookmark(
        url=url, title=title, add_date=1, source_path=FolderPath.from_string(path)
    )


def _tax(*, rules: tuple[Rule, ...] = (), pins: tuple[str, ...] = ()) -> Taxonomy:
    return Taxonomy(
        version=1,
        intents=(Intent(name="work"), Intent(name="fun")),
        pins=tuple(FolderPath.from_string(p) for p in pins),
        rules=rules,
        reference_root=FolderPath.from_string("other/Reference"),
    )


def test_pinned_bookmark_stays_put_via_pin() -> None:
    """Given a bookmark under a pin, When assigned, Then via is pin."""
    tax = _tax(pins=("bookmarks_bar/Daily",))
    bm = _bm("https://example.com/x", "bookmarks_bar/Daily/Sub")
    outcome = assign_by_rules(bm, tax)
    assert outcome is not None
    assert outcome.via == "pin"
    assert outcome.folder == FolderPath.from_string("bookmarks_bar/Daily/Sub")


def test_domain_rule_matches_and_sets_folder_and_ref() -> None:
    """Given a domain rule, When it matches, Then folder and ref are set."""
    rule = Rule(
        match=RuleMatch(domain="example.com"),
        folder=FolderPath.from_string("work/dev"),
        ref=FolderPath.from_string("technical/dev"),
    )
    tax = _tax(rules=(rule,))
    outcome = assign_by_rules(_bm("https://sub.example.com/a", "other"), tax)
    assert outcome is not None
    assert outcome.via == "rule"
    assert outcome.folder == FolderPath.from_string("work/dev")
    assert outcome.ref == FolderPath.from_string("technical/dev")


def test_first_matching_rule_wins() -> None:
    """Given two matching rules, When assigned, Then the first one wins."""
    first = Rule(
        match=RuleMatch(domain="example.com"),
        folder=FolderPath.from_string("work/one"),
    )
    second = Rule(
        match=RuleMatch(domain="example.com"),
        folder=FolderPath.from_string("work/two"),
    )
    tax = _tax(rules=(first, second))
    outcome = assign_by_rules(_bm("https://example.com/a", "other"), tax)
    assert outcome is not None
    assert outcome.folder == FolderPath.from_string("work/one")


def test_url_prefix_and_title_regex_criteria() -> None:
    """Given prefix + regex, When both match, Then the rule applies."""
    rule = Rule(
        match=RuleMatch(
            domain="example.com", url_prefix="/dev", title_regex=r"(?i)tool"
        ),
        folder=FolderPath.from_string("work/dev"),
    )
    tax = _tax(rules=(rule,))
    hit = _bm("https://example.com/dev/x", "other", title="My Tool")
    miss = _bm("https://example.com/other", "other", title="My Tool")
    assert assign_by_rules(hit, tax) is not None
    assert assign_by_rules(miss, tax) is None


def test_stay_put_when_already_in_intent_path() -> None:
    """Given a bookmark in an intent path, When assigned, Then via is stay."""
    tax = _tax()
    bm = _bm("https://example.com/a", "work/dev")
    outcome = assign_by_rules(bm, tax)
    assert outcome is not None
    assert outcome.via == "stay"
    assert outcome.folder == FolderPath.from_string("work/dev")


def test_stay_put_only_applies_to_bar_scoped_intent_paths() -> None:
    """Given an intent-shaped path under 'other', When assigned, Then residue."""
    tax = _tax()
    # 'other/work/thing' is NOT a bar-scoped intent home; must not stay put.
    bm = _bm("https://example.com/a", "other/work/thing")
    assert assign_by_rules(bm, tax) is None
    # The same shape under the bar does stay put.
    bar_bm = _bm("https://example.com/a", "bookmarks_bar/work/thing")
    outcome = assign_by_rules(bar_bm, tax)
    assert outcome is not None
    assert outcome.via == "stay"
    assert outcome.folder == FolderPath.from_string("work/thing")


def test_restructure_disables_stay_put() -> None:
    """Given restructure, When a bookmark is in an intent path, Then residue."""
    tax = _tax()
    bm = _bm("https://example.com/a", "work/dev")
    assert assign_by_rules(bm, tax, restructure=True) is None


def test_unmatched_bookmark_is_residue() -> None:
    """Given no pin/rule/intent path, When assigned, Then None (residue)."""
    tax = _tax()
    bm = _bm("https://example.com/a", "bookmarks_bar/Random")
    assert assign_by_rules(bm, tax) is None
