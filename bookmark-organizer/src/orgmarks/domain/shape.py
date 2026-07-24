"""Skinny-tree shape invariants, enforced mechanically by pure code.

The LLM proposes *where* a bookmark belongs; the *shape* is deterministic:

- Every folder is a **hub** (has subfolders) or a **leaf** (links only).
- A hub holds at most ``max_umbrella_links`` direct links, and only
  root-of-concept URLs (path depth <= 1, host matching the folder's concept).
- Emission is umbrella-links-then-subfolders, nothing after the folders
  (handled by the Netscape emitter).
- A non-umbrella link stranded in a hub is wrapped into its own single-element
  subfolder. Single-link leaves are valid by design.
"""

from __future__ import annotations

import re
from dataclasses import replace
from urllib.parse import urlsplit

from orgmarks.domain.model import Bookmark, Folder


def _path_depth(url: str) -> int:
    return len([seg for seg in urlsplit(url).path.split("/") if seg])


def _concept_token(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _host_matches_concept(url: str, folder_name: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    token = _concept_token(folder_name)
    if not token:
        return False
    labels = host.split(".")
    return token in labels or token == host.replace(".", "")


def is_umbrella_link(bookmark: Bookmark, folder_name: str) -> bool:
    """True if ``bookmark`` may sit directly atop the hub named ``folder_name``."""
    return _path_depth(bookmark.url) <= 1 and _host_matches_concept(
        bookmark.url, folder_name
    )


def _wrapper_name(bookmark: Bookmark) -> str:
    title = bookmark.title.strip()
    if title and not title.lower().startswith(("http://", "https://")):
        return title
    host = urlsplit(bookmark.url).hostname or bookmark.url
    return host


def _wrap(bookmark: Bookmark) -> Folder:
    return Folder(name=_wrapper_name(bookmark), bookmarks=(bookmark,))


def check_shape(folder: Folder, *, max_umbrella_links: int) -> list[str]:
    """Return a list of shape violations for ``folder`` and its descendants."""
    violations: list[str] = []
    if folder.is_hub:
        umbrella = [b for b in folder.bookmarks if is_umbrella_link(b, folder.name)]
        stranded = [b for b in folder.bookmarks if not is_umbrella_link(b, folder.name)]
        for bm in stranded:
            violations.append(
                f"stranded non-umbrella link {bm.url!r} in hub {folder.name!r}"
            )
        if len(umbrella) > max_umbrella_links:
            violations.append(
                f"hub {folder.name!r} has {len(umbrella)} umbrella links "
                f"(max {max_umbrella_links})"
            )
    for sub in folder.subfolders:
        violations.extend(check_shape(sub, max_umbrella_links=max_umbrella_links))
    return violations


def enforce_local(folder: Folder, *, max_umbrella_links: int) -> Folder:
    """Fix ``folder``'s own hub/leaf shape, assuming its subfolders are fine.

    A leaf is returned unchanged. In a hub the direct links are partitioned:
    up to ``max_umbrella_links`` root-of-concept links stay as umbrella links;
    every other stranded link is wrapped into its own single-element subfolder.
    Does not recurse -- callers apply it bottom-up.
    """
    if folder.is_leaf:
        return folder

    umbrella: list[Bookmark] = []
    stranded: list[Bookmark] = []
    for bm in folder.bookmarks:
        if len(umbrella) < max_umbrella_links and is_umbrella_link(bm, folder.name):
            umbrella.append(bm)
        else:
            stranded.append(bm)

    wrappers = tuple(_wrap(bm) for bm in stranded)
    return replace(
        folder,
        bookmarks=tuple(umbrella),
        subfolders=folder.subfolders + wrappers,
    )


def enforce_shape(folder: Folder, *, max_umbrella_links: int) -> Folder:
    """Return a copy of ``folder`` and its descendants satisfying every invariant."""
    fixed_subs = tuple(
        enforce_shape(sub, max_umbrella_links=max_umbrella_links)
        for sub in folder.subfolders
    )
    return enforce_local(
        replace(folder, subfolders=fixed_subs), max_umbrella_links=max_umbrella_links
    )
