"""The Rule Engine: deterministic classification before the LLM.

Pure function of a bookmark and the taxonomy. Order: pins first, then rules
(first match wins, human before learned), then the churn minimizer (a bookmark
already in a valid intent path stays put unless ``restructure``). Everything
unmatched is the residue handed to the classifier.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from orgmarks.domain.model import Bookmark, FolderPath, Rule, RuleMatch
from orgmarks.domain.taxonomy import Taxonomy

# Intents live under the Bookmarks Bar; only this root is stripped before the
# intent-path check. A folder named like an intent under "other"/"synced" is
# coincidental, not an intent home, so it stays residue.
_BAR_ROOT = "bookmarks_bar"

RuleVia = Literal["pin", "rule", "stay"]


@dataclass(frozen=True, slots=True)
class RuleOutcome:
    """Where a rule (or pin, or stay) places a bookmark."""

    folder: FolderPath
    ref: FolderPath | None
    via: RuleVia


def _host(url: str) -> str:
    return urlsplit(url).hostname or ""


def _domain_matches(host: str, domain: str) -> bool:
    host = host.lower()
    domain = domain.lower()
    return host == domain or host.endswith("." + domain)


def _match(bookmark: Bookmark, match: RuleMatch) -> bool:
    """True if every specified criterion matches (AND); empty match is a catch-all."""
    if match.domain is not None and not _domain_matches(
        _host(bookmark.url), match.domain
    ):
        return False
    if match.url_prefix is not None:
        if not urlsplit(bookmark.url).path.startswith(match.url_prefix):
            return False
    if (
        match.title_regex is not None
        and re.search(match.title_regex, bookmark.title) is None
    ):
        return False
    return True


def _under_pin(bookmark: Bookmark, taxonomy: Taxonomy) -> bool:
    return any(bookmark.source_path.is_under(pin) for pin in taxonomy.pins)


def intent_relative(path: FolderPath) -> FolderPath:
    """Drop a leading ``bookmarks_bar`` root if present.

    Source paths are root-prefixed; intent paths in the taxonomy are not. Only
    the bar root is stripped: intents are bar-scoped, so an intent-shaped path
    under ``other``/``synced`` is not an intent home and must not stay put.
    """
    if path.depth >= 1 and path.parts[0] == _BAR_ROOT:
        return FolderPath(path.parts[1:])
    return path


def _first_rule(bookmark: Bookmark, taxonomy: Taxonomy) -> Rule | None:
    for rule in taxonomy.rules:
        if _match(bookmark, rule.match):
            return rule
    return None


def assign_by_rules(
    bookmark: Bookmark, taxonomy: Taxonomy, *, restructure: bool = False
) -> RuleOutcome | None:
    """Classify one bookmark deterministically, or None if it is residue."""
    if _under_pin(bookmark, taxonomy):
        return RuleOutcome(folder=bookmark.source_path, ref=None, via="pin")

    rule = _first_rule(bookmark, taxonomy)
    if rule is not None:
        return RuleOutcome(folder=rule.folder, ref=rule.ref, via="rule")

    relative = intent_relative(bookmark.source_path)
    if not restructure and taxonomy.is_intent_path(relative):
        return RuleOutcome(folder=relative, ref=None, via="stay")

    return None
