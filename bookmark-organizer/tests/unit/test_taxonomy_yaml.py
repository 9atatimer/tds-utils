"""Unit tests for taxonomy.yml parsing, validation, and learned-rule writes."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from orgmarks.adapters.taxonomy_yaml import (
    load_taxonomy,
    load_taxonomy_text,
    write_learned_rules,
)
from orgmarks.domain.model import FolderPath, Rule, RuleMatch

EXAMPLE = Path(__file__).resolve().parent.parent.parent / "taxonomy.example.yml"


def test_example_file_parses_to_taxonomy() -> None:
    """Given the shipped example, When loaded, Then a Taxonomy is built."""
    tax = load_taxonomy(EXAMPLE)
    assert tax.version == 1
    assert tax.intent_names() == ("work", "fun", "self-education", "writing")
    assert tax.reference_root == FolderPath.from_string("other/Reference")
    assert tax.pins == (FolderPath.from_string("bookmarks_bar/Daily"),)
    assert tax.llm is not None
    assert tax.llm.provider == "claude-cli"
    assert tax.max_umbrella_links == 3


def test_rules_sort_human_before_learned() -> None:
    """Given mixed rule sources, When loaded, Then human rules come first."""
    text = """
version: 1
intents:
  - name: work
reference:
  root: other/Reference
rules:
  - match: {domain: a.example.com}
    folder: fun/a
    source: learned
  - match: {domain: b.example.com}
    folder: work/b
    source: human
"""
    tax = load_taxonomy_text(text)
    assert [r.source for r in tax.rules] == ["human", "learned"]


def test_absent_llm_block_yields_none() -> None:
    """Given no llm block, When loaded, Then Taxonomy.llm is None."""
    text = """
version: 1
intents:
  - name: work
reference:
  root: other/Reference
"""
    tax = load_taxonomy_text(text)
    assert tax.llm is None


def test_invalid_taxonomy_raises_validation_error() -> None:
    """Given an unknown key, When loaded, Then a ValidationError is raised."""
    text = """
version: 1
intents:
  - name: work
reference:
  root: other/Reference
bogus_key: 3
"""
    with pytest.raises(ValidationError):
        load_taxonomy_text(text)


def test_missing_required_field_raises() -> None:
    """Given no reference block, When loaded, Then validation fails."""
    text = """
version: 1
intents:
  - name: work
"""
    with pytest.raises(ValidationError):
        load_taxonomy_text(text)


def test_write_learned_rules_appends_and_preserves_comment(tmp_path: Path) -> None:
    """Given a taxonomy with a comment, When a rule is written, Then both survive."""
    path = tmp_path / "taxonomy.yml"
    path.write_text(
        "# my taxonomy\n"
        "version: 1\n"
        "intents:\n"
        "  - name: work\n"
        "reference:\n"
        "  root: other/Reference\n"
        "rules: []\n"
    )
    rule = Rule(
        match=RuleMatch(domain="news.example.com"),
        folder=FolderPath.from_string("fun/news"),
        ref=FolderPath.from_string("culture/news"),
        source="learned",
    )
    write_learned_rules(path, [rule])
    out = path.read_text()
    assert "# my taxonomy" in out
    tax = load_taxonomy(path)
    assert any(r.match.domain == "news.example.com" for r in tax.rules)


def test_write_learned_rules_is_idempotent(tmp_path: Path) -> None:
    """Given the same rule twice, When written twice, Then it appears once."""
    path = tmp_path / "taxonomy.yml"
    path.write_text(
        "version: 1\n"
        "intents:\n"
        "  - name: work\n"
        "reference:\n"
        "  root: other/Reference\n"
        "rules: []\n"
    )
    rule = Rule(
        match=RuleMatch(domain="news.example.com"),
        folder=FolderPath.from_string("fun/news"),
        source="learned",
    )
    write_learned_rules(path, [rule])
    write_learned_rules(path, [rule])
    tax = load_taxonomy(path)
    hits = [r for r in tax.rules if r.match.domain == "news.example.com"]
    assert len(hits) == 1
