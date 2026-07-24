"""Unit tests for the pipeline state machine and degrade behavior."""

from __future__ import annotations

from collections.abc import Sequence

from orgmarks.adapters.fake_classifier import FakeClassifier
from orgmarks.app.pipeline import run
from orgmarks.domain.errors import InfrastructureError
from orgmarks.domain.model import (
    Bookmark,
    BookmarkTree,
    Folder,
    FolderPath,
    Rule,
    RuleMatch,
)
from orgmarks.domain.taxonomy import Intent, LlmConfig, Taxonomy
from orgmarks.ports.classifier import ClassifyResult


def _bm(url: str, path: str = "bookmarks_bar", *, title: str = "t") -> Bookmark:
    return Bookmark(
        url=url, title=title, add_date=1, source_path=FolderPath.from_string(path)
    )


def _tree(bookmarks: list[Bookmark]) -> BookmarkTree:
    bar = Folder(name="bookmarks_bar", bookmarks=tuple(bookmarks))
    return BookmarkTree(roots=(("bookmarks_bar", bar),))


def _tax(*, with_llm: bool, rules: tuple[Rule, ...] = ()) -> Taxonomy:
    return Taxonomy(
        version=1,
        intents=(Intent(name="work"), Intent(name="fun")),
        pins=(),
        rules=rules,
        reference_root=FolderPath.from_string("other/Reference"),
        llm=LlmConfig(provider="fake", confidence_threshold=0.7) if with_llm else None,
        triage_folder="_triage",
    )


def _all_urls(tree: BookmarkTree, exclude_ref: FolderPath) -> set[str]:
    found: set[str] = set()

    def walk(folder: Folder, path: FolderPath) -> None:
        if path == exclude_ref:
            return
        found.update(b.url for b in folder.bookmarks)
        for sub in folder.subfolders:
            walk(sub, path.child(sub.name))

    for name, folder in tree.roots:
        walk(folder, FolderPath((name,)))
    return found


def test_rule_hit_places_bookmark_under_bar() -> None:
    """Given a matching rule, When run, Then the bookmark lands in its intent."""
    rule = Rule(
        match=RuleMatch(domain="example.com"),
        folder=FolderPath.from_string("work/dev"),
        ref=FolderPath.from_string("technical/dev"),
    )
    tax = _tax(with_llm=False, rules=(rule,))
    result = run(_tree([_bm("https://example.com/a")]), tax, None, mode="plan")
    move = result.plan.moves[0]
    assert move.via == "rule"
    assert move.folder == FolderPath.from_string("bookmarks_bar/work/dev")


def test_high_confidence_llm_result_is_learned_back() -> None:
    """Given a confident LLM result, When run, Then a learned rule appears."""
    bm = _bm("https://sub.example.com/x", "bookmarks_bar/Loose")
    result_row = ClassifyResult(
        url=bm.url,
        folder=FolderPath.from_string("work/dev"),
        ref=FolderPath.from_string("technical/dev"),
        confidence=0.95,
    )
    classifier = FakeClassifier({bm.url: result_row})
    tax = _tax(with_llm=True)
    result = run(_tree([bm]), tax, classifier, mode="plan")
    assert any(r.source == "learned" for r in result.plan.learned_rules)
    llm_move = next(m for m in result.plan.moves if m.via == "llm")
    assert llm_move.folder == FolderPath.from_string("bookmarks_bar/work/dev")


def test_low_confidence_result_goes_to_triage() -> None:
    """Given a low-confidence result, When run, Then the bookmark is triaged."""
    bm = _bm("https://sub.example.com/x", "bookmarks_bar/Loose")
    classifier = FakeClassifier()  # default confidence 0.0
    tax = _tax(with_llm=True)
    result = run(_tree([bm]), tax, classifier, mode="plan")
    triaged = next(m for m in result.plan.moves if m.via == "triage")
    assert triaged.folder == FolderPath.from_string("bookmarks_bar/_triage")


def test_absent_llm_block_skips_classify_and_triages_residue() -> None:
    """Given no llm block, When run, Then residue is triaged, no crash."""
    bm = _bm("https://sub.example.com/x", "bookmarks_bar/Loose")
    tax = _tax(with_llm=False)
    result = run(_tree([bm]), tax, None, mode="plan")
    assert result.plan.moves[0].via == "triage"


def test_unreachable_classifier_degrades_to_rules_only() -> None:
    """Given a classifier that raises, When run, Then it degrades gracefully."""

    class _Boom:
        def classify(
            self, batch: Sequence[Bookmark], *, intents: object, skeleton: str
        ) -> list[ClassifyResult]:
            raise InfrastructureError("provider down")

    bm = _bm("https://sub.example.com/x", "bookmarks_bar/Loose")
    tax = _tax(with_llm=True)
    result = run(_tree([bm]), tax, _Boom(), mode="plan")
    assert result.plan.moves[0].via == "triage"
    assert "rules-only" in result.report


def test_hostless_confident_result_places_without_learned_rule() -> None:
    """Given a confident file:// result, When run, Then no rule is learned."""
    bm = _bm("file:///home/user/notes.html", "bookmarks_bar/Loose")
    row = ClassifyResult(
        url=bm.url,
        folder=FolderPath.from_string("work/dev"),
        ref=FolderPath.from_string("technical/dev"),
        confidence=0.95,
    )
    tax = _tax(with_llm=True)
    result = run(_tree([bm]), tax, FakeClassifier({bm.url: row}), mode="plan")
    assert next(m for m in result.plan.moves if m.via == "llm")
    assert result.plan.learned_rules == ()


def test_zero_confidence_never_counts_as_success() -> None:
    """Given threshold 0.0, When a 0.0 result arrives, Then it is triaged."""
    bm = _bm("https://sub.example.com/x", "bookmarks_bar/Loose")
    row = ClassifyResult(
        url=bm.url,
        folder=FolderPath.from_string("work/dev"),
        ref=FolderPath.from_string("technical/dev"),
        confidence=0.0,
    )
    tax = Taxonomy(
        version=1,
        intents=(Intent(name="work"),),
        pins=(),
        rules=(),
        reference_root=FolderPath.from_string("other/Reference"),
        llm=LlmConfig(provider="fake", confidence_threshold=0.0),
        triage_folder="_triage",
    )
    result = run(_tree([bm]), tax, FakeClassifier({bm.url: row}), mode="plan")
    assert result.plan.moves[0].via == "triage"
    assert result.plan.learned_rules == ()


def test_already_rooted_llm_folder_is_not_double_prefixed() -> None:
    """Given a classifier that returns a rooted path, When run, Then no double bar."""
    bm = _bm("https://sub.example.com/x", "bookmarks_bar/Loose")
    row = ClassifyResult(
        url=bm.url,
        folder=FolderPath.from_string("bookmarks_bar/work/dev"),
        ref=FolderPath.from_string("technical/dev"),
        confidence=0.95,
    )
    tax = _tax(with_llm=True)
    result = run(_tree([bm]), tax, FakeClassifier({bm.url: row}), mode="plan")
    llm_move = next(m for m in result.plan.moves if m.via == "llm")
    assert llm_move.folder == FolderPath.from_string("bookmarks_bar/work/dev")


def test_reference_copies_are_not_re_ingested() -> None:
    """Given prior output with a Reference copy, When run, Then no double-file."""
    rule = Rule(
        match=RuleMatch(domain="example.com"),
        folder=FolderPath.from_string("work/dev"),
        ref=FolderPath.from_string("technical/dev"),
    )
    tax = _tax(with_llm=False, rules=(rule,))
    intent_copy = _bm("https://example.com/a", "bookmarks_bar/work/dev")
    reference_copy = _bm("https://example.com/a", "other/Reference/technical/dev")
    tree = BookmarkTree(
        roots=(
            (
                "bookmarks_bar",
                Folder(name="bookmarks_bar", bookmarks=(intent_copy,)),
            ),
            ("other", Folder(name="other", bookmarks=(reference_copy,))),
        )
    )
    result = run(tree, tax, None, mode="plan")
    # The URL is filed once (its Reference copy was treated as derived).
    assert len(result.plan.moves) == 1
    outside = _all_urls(result.organized, tax.reference_root)
    assert outside == {"https://example.com/a"}


def test_assignment_colliding_with_pin_is_triaged() -> None:
    """Given a rule targeting a pinned path, When run, Then it is triaged."""
    rule = Rule(
        match=RuleMatch(domain="example.com"),
        folder=FolderPath.from_string("Daily/sub"),
        ref=FolderPath.from_string("technical/dev"),
    )
    tax = Taxonomy(
        version=1,
        intents=(Intent(name="work"),),
        pins=(FolderPath.from_string("bookmarks_bar/Daily"),),
        rules=(rule,),
        reference_root=FolderPath.from_string("other/Reference"),
        triage_folder="_triage",
    )
    bm = _bm("https://example.com/x", "bookmarks_bar/Loose")
    result = run(_tree([bm]), tax, None, mode="plan")
    assert result.plan.moves[0].via == "triage"


def test_pipeline_is_lossless_and_reference_exhaustive() -> None:
    """Given a mix, When run, Then every url appears in tree and Reference."""
    rule = Rule(
        match=RuleMatch(domain="example.com"),
        folder=FolderPath.from_string("work/dev"),
        ref=FolderPath.from_string("technical/dev"),
    )
    tax = _tax(with_llm=False, rules=(rule,))
    marks = [_bm("https://example.com/a"), _bm("https://other.example.com/b")]
    result = run(_tree(marks), tax, None, mode="plan")
    outside = _all_urls(result.organized, tax.reference_root)
    assert outside == {b.url for b in marks}


def test_second_run_needs_no_llm_after_learn_back() -> None:
    """Given learned rules re-applied, When run again, Then no residue triaged."""
    bm = _bm("https://sub.example.com/x", "bookmarks_bar/Loose")
    row = ClassifyResult(
        url=bm.url,
        folder=FolderPath.from_string("work/dev"),
        ref=FolderPath.from_string("technical/dev"),
        confidence=0.95,
    )
    tax = _tax(with_llm=True)
    first = run(_tree([bm]), tax, FakeClassifier({bm.url: row}), mode="plan")
    learned = first.plan.learned_rules
    # Re-run with the learned rules folded in and NO classifier.
    tax2 = _tax(with_llm=False, rules=learned)
    second = run(_tree([bm]), tax2, None, mode="plan")
    assert second.plan.moves[0].via == "rule"
