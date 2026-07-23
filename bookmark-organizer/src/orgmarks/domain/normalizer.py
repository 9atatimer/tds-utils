"""Normalizer: per-folder dedupe, compare-only canonicalization, prune.

Pure domain logic over a BookmarkTree. Two invariants matter here:

- **Losslessness** is not weakened: the stored ``Bookmark.url`` is never
  rewritten. Canonicalization is used only to decide whether two URLs are the
  same for dedupe.
- **Per-folder uniqueness**: within a single folder no canonical URL appears
  twice. The same URL in *different* folders is a deliberate breadcrumb and is
  preserved (reported as info only). Subtrees under a pin pass through verbatim.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from orgmarks.domain.model import (
    Bookmark,
    BookmarkTree,
    DedupeGroup,
    Folder,
    FolderPath,
    RootName,
)

# Query-parameter keys stripped for comparison (never from the stored URL).
_TRACKING_KEYS = frozenset(
    {"fbclid", "gclid", "mc_eid", "mc_cid", "igshid", "_ga", "yclid", "msclkid"}
)


@dataclass(frozen=True, slots=True)
class CrossFolderDup:
    """A canonical URL that appears in more than one folder (a breadcrumb)."""

    url: str
    paths: tuple[FolderPath, ...]


@dataclass(frozen=True, slots=True)
class NormalizeResult:
    """The deduped tree plus what changed, for the plan report."""

    tree: BookmarkTree
    dedupes: tuple[DedupeGroup, ...]
    pruned: tuple[FolderPath, ...]
    cross_folder_dups: tuple[CrossFolderDup, ...]


def _is_tracking_key(key: str) -> bool:
    low = key.lower()
    return low.startswith("utm_") or low in _TRACKING_KEYS


def canonicalize_for_compare(url: str) -> str:
    """Return a comparison key for ``url``; the stored URL is never changed.

    Strips tracking query params (utm_*, fbclid, gclid, ...) and a single
    trailing slash. Used only to decide URL equality for dedupe.
    """
    parts = urlsplit(url)
    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not _is_tracking_key(k)
    ]
    query = urlencode(kept)
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme, parts.netloc, path, query, ""))


def _looks_like_url(title: str) -> bool:
    stripped = title.strip().lower()
    return stripped.startswith(("http://", "https://"))


def _best_title(group: Sequence[Bookmark]) -> str:
    """Longest non-URL-shaped title, else the longest title."""
    non_url = [bm.title for bm in group if not _looks_like_url(bm.title)]
    pool = non_url or [bm.title for bm in group]
    return max(pool, key=len)


def _oldest(group: Sequence[Bookmark]) -> Bookmark:
    """The copy with the oldest known add_date (0 = unknown, sorts last)."""
    return min(group, key=lambda bm: bm.add_date if bm.add_date > 0 else float("inf"))


def _dedupe_bookmarks(
    bookmarks: Sequence[Bookmark],
) -> tuple[tuple[Bookmark, ...], tuple[DedupeGroup, ...]]:
    """Collapse exact-canonical duplicates within one folder's direct links."""
    order: list[str] = []
    groups: dict[str, list[Bookmark]] = {}
    for bm in bookmarks:
        key = canonicalize_for_compare(bm.url)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(bm)

    survivors: list[Bookmark] = []
    dedupes: list[DedupeGroup] = []
    for key in order:
        members = groups[key]
        oldest = _oldest(members)
        survivor = replace(oldest, title=_best_title(members))
        survivors.append(survivor)
        if len(members) > 1:
            dropped = tuple(bm for bm in members if bm is not oldest)
            dedupes.append(DedupeGroup(kept=survivor, dropped=dropped))
    return tuple(survivors), tuple(dedupes)


def _is_pinned(path: FolderPath, pins: Sequence[FolderPath]) -> bool:
    return any(path.is_under(pin) for pin in pins)


def _normalize_folder(
    folder: Folder,
    path: FolderPath,
    pins: Sequence[FolderPath],
    dedupes: list[DedupeGroup],
    pruned: list[FolderPath],
    *,
    is_root: bool,
) -> Folder | None:
    """Return the normalized folder, or None if it should be pruned."""
    if _is_pinned(path, pins):
        return folder

    survivors, folder_dedupes = _dedupe_bookmarks(folder.bookmarks)
    dedupes.extend(folder_dedupes)

    new_subs: list[Folder] = []
    for sub in folder.subfolders:
        sub_path = path.child(sub.name)
        result = _normalize_folder(sub, sub_path, pins, dedupes, pruned, is_root=False)
        if result is None:
            pruned.append(sub_path)
        else:
            new_subs.append(result)

    normalized = replace(folder, subfolders=tuple(new_subs), bookmarks=survivors)
    if not is_root and not normalized.bookmarks and not normalized.subfolders:
        return None
    return normalized


def _collect_cross_folder(tree: BookmarkTree) -> tuple[CrossFolderDup, ...]:
    """Find canonical URLs that survive in more than one folder."""
    seen: dict[str, list[FolderPath]] = {}
    for bm in tree.iter_bookmarks():
        key = canonicalize_for_compare(bm.url)
        seen.setdefault(key, [])
        if bm.source_path not in seen[key]:
            seen[key].append(bm.source_path)
    return tuple(
        CrossFolderDup(url=key, paths=tuple(paths))
        for key, paths in seen.items()
        if len(paths) > 1
    )


def normalize(tree: BookmarkTree, *, pins: Sequence[FolderPath]) -> NormalizeResult:
    """Dedupe per folder, prune empties, and report cross-folder breadcrumbs."""
    dedupes: list[DedupeGroup] = []
    pruned: list[FolderPath] = []
    new_roots: list[tuple[RootName, Folder]] = []
    for root_name, folder in tree.roots:
        base = FolderPath((root_name,))
        result = _normalize_folder(folder, base, pins, dedupes, pruned, is_root=True)
        assert result is not None  # roots are never pruned
        new_roots.append((root_name, result))
    new_tree = BookmarkTree(roots=tuple(new_roots))
    return NormalizeResult(
        tree=new_tree,
        dedupes=tuple(dedupes),
        pruned=tuple(pruned),
        cross_folder_dups=_collect_cross_folder(new_tree),
    )
