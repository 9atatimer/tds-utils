"""The pipeline: LOAD -> NORMALIZE -> RULES -> CLASSIFY -> PLAN -> EMIT.

The composition root. The tree is already loaded by an adapter; this module
wires the pure stages together and degrades to rules-only when the LLM is
absent or unreachable (residue falls to ``_triage``; the run never crashes).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

import structlog

from orgmarks.app.report import format_report
from orgmarks.domain.errors import InfrastructureError
from orgmarks.domain.model import (
    Assignment,
    Bookmark,
    BookmarkTree,
    Folder,
    FolderPath,
    Plan,
    Rule,
    RuleMatch,
)
from orgmarks.domain.normalizer import NormalizeResult, normalize
from orgmarks.domain.planner import build_organized_tree, build_plan
from orgmarks.domain.rules import RuleOutcome, assign_by_rules
from orgmarks.domain.taxonomy import Taxonomy
from orgmarks.ports.classifier import Classifier, ClassifyResult

_BATCH_SIZE = 50
_UNCATEGORIZED = FolderPath(("uncategorized",))
_BAR = "bookmarks_bar"

_log = structlog.get_logger()

Mode = Literal["plan", "apply"]


@dataclass(frozen=True, slots=True)
class PipelineResult:
    """The outcome of a run: the Plan, the organized tree, and the report."""

    plan: Plan
    organized: BookmarkTree
    report: str


def _root_under_bar(path: FolderPath) -> FolderPath:
    return FolderPath((_BAR, *path.parts))


def _assignment_from_rules(bookmark: Bookmark, outcome: RuleOutcome) -> Assignment:
    if outcome.via == "pin":
        folder = bookmark.source_path
    else:  # rule or stay: intent-relative, rooted under the bar
        folder = _root_under_bar(outcome.folder)
    ref = outcome.ref if outcome.ref is not None else _UNCATEGORIZED
    return Assignment(
        bookmark=bookmark, folder=folder, ref=ref, confidence=1.0, via=outcome.via
    )


def _triage_assignment(
    bookmark: Bookmark, taxonomy: Taxonomy, *, ref: FolderPath | None = None
) -> Assignment:
    return Assignment(
        bookmark=bookmark,
        folder=FolderPath((_BAR, taxonomy.triage_folder)),
        ref=ref or _UNCATEGORIZED,
        confidence=0.0,
        via="triage",
    )


def _llm_assignment(bookmark: Bookmark, result: ClassifyResult) -> Assignment:
    return Assignment(
        bookmark=bookmark,
        folder=_root_under_bar(result.folder),
        ref=result.ref,
        confidence=result.confidence,
        via="llm",
    )


def _generalize(bookmark: Bookmark, result: ClassifyResult) -> Rule:
    host = urlsplit(bookmark.url).hostname or ""
    return Rule(
        match=RuleMatch(domain=host),
        folder=result.folder,
        ref=result.ref,
        source="learned",
    )


def _dedupe_rules(rules: Sequence[Rule]) -> tuple[Rule, ...]:
    seen: set[tuple[str, str, str, str, str]] = set()
    unique: list[Rule] = []
    for rule in rules:
        key = (
            rule.match.domain or "",
            rule.match.url_prefix or "",
            rule.match.title_regex or "",
            str(rule.folder),
            str(rule.ref) if rule.ref else "",
        )
        if key not in seen:
            seen.add(key)
            unique.append(rule)
    return tuple(unique)


def _skeleton(tree: BookmarkTree) -> str:
    lines: list[str] = []

    def walk(folder: Folder, path: FolderPath) -> None:
        direct = len(folder.bookmarks)
        lines.append(f"{path} ({direct} links)")
        for sub in folder.subfolders:
            walk(sub, path.child(sub.name))

    for name, folder in tree.roots:
        walk(folder, FolderPath((name,)))
    return "\n".join(lines)


def _classify_residue(
    classifier: Classifier, residue: Sequence[Bookmark], taxonomy: Taxonomy
) -> list[ClassifyResult]:
    skeleton = _skeleton(build_organized_tree(_empty_tree(), taxonomy, ()))
    results: list[ClassifyResult] = []
    for start in range(0, len(residue), _BATCH_SIZE):
        batch = residue[start : start + _BATCH_SIZE]
        results.extend(
            classifier.classify(batch, intents=taxonomy.intents, skeleton=skeleton)
        )
    return results


def _empty_tree() -> BookmarkTree:
    return BookmarkTree(roots=())


def _compose_report(
    plan: Plan,
    norm: NormalizeResult,
    new_areas: Counter[str],
    *,
    degraded: bool,
) -> str:
    parts = [format_report(plan)]
    parts.append("")
    parts.append(f"cross-folder duplicates (kept): {len(norm.cross_folder_dups)}")
    parts.append(f"empty folders pruned: {len(norm.pruned)}")
    if new_areas:
        parts.append("")
        parts.append("proposed new areas:")
        for name, count in sorted(new_areas.items()):
            parts.append(f"  - new area: {name}, {count} bookmarks")
    if degraded:
        parts.append("")
        parts.append("NOTE: LLM unavailable; ran rules-only, residue -> _triage.")
    return "\n".join(parts)


def run(
    tree: BookmarkTree,
    taxonomy: Taxonomy,
    classifier: Classifier | None,
    *,
    mode: Mode,
    restructure: bool = False,
) -> PipelineResult:
    """Run the full pipeline and return the plan, organized tree, and report."""
    norm = normalize(tree, pins=taxonomy.pins)

    assignments: list[Assignment] = []
    residue: list[Bookmark] = []
    for bookmark in norm.tree.iter_bookmarks():
        outcome = assign_by_rules(bookmark, taxonomy, restructure=restructure)
        if outcome is None:
            residue.append(bookmark)
        else:
            assignments.append(_assignment_from_rules(bookmark, outcome))

    learned: list[Rule] = []
    new_areas: Counter[str] = Counter()
    degraded = False

    if residue:
        llm = taxonomy.llm
        results: list[ClassifyResult] | None = None
        if llm is not None and classifier is not None:
            try:
                results = _classify_residue(classifier, residue, taxonomy)
            except InfrastructureError:
                _log.warning("classifier_unreachable", degrade="rules-only")
                degraded = True
        if results is None:
            for bookmark in residue:
                assignments.append(_triage_assignment(bookmark, taxonomy))
        else:
            assert llm is not None
            threshold = llm.confidence_threshold
            for bookmark, result in zip(residue, results, strict=True):
                if result.proposed_new_folder:
                    new_areas[result.proposed_new_folder] += 1
                if result.confidence >= threshold:
                    assignments.append(_llm_assignment(bookmark, result))
                    learned.append(_generalize(bookmark, result))
                else:
                    assignments.append(
                        _triage_assignment(bookmark, taxonomy, ref=result.ref)
                    )

    learned_rules = _dedupe_rules(learned)
    plan = build_plan(norm.tree, taxonomy, assignments, norm.dedupes, learned_rules)
    organized = build_organized_tree(norm.tree, taxonomy, assignments)
    report = _compose_report(plan, norm, new_areas, degraded=degraded)
    return PipelineResult(plan=plan, organized=organized, report=report)
