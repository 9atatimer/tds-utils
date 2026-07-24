"""Chrome ``Bookmarks`` JSON: the live-profile file, read-only.

A convenience input (``--from-profile``) that skips the manual export step.
GUIDs and ``date_added`` are preserved. This adapter NEVER writes the profile.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from orgmarks.domain.model import (
    Bookmark,
    BookmarkTree,
    Folder,
    FolderPath,
    RootName,
)

# Chrome stores date_added as microseconds since 1601-01-01 (Windows epoch).
_WINDOWS_TO_UNIX_SECONDS = 11644473600

# Chrome roots key -> our RootName.
_ROOT_KEYS: tuple[tuple[str, RootName], ...] = (
    ("bookmark_bar", "bookmarks_bar"),
    ("other", "other"),
    ("synced", "synced"),
)


def _chrome_date_to_epoch(raw: object) -> int:
    """Convert a Chrome microsecond timestamp string to unix epoch seconds."""
    if not isinstance(raw, str) or not raw.strip():
        return 0
    try:
        micros = int(raw)
    except ValueError:
        return 0
    if micros <= 0:
        return 0
    return micros // 1_000_000 - _WINDOWS_TO_UNIX_SECONDS


def _node_to_folder(node: dict[str, Any], path: FolderPath, name: str) -> Folder:
    """Convert a Chrome folder node to a frozen Folder rooted at ``path``."""
    bookmarks: list[Bookmark] = []
    subfolders: list[Folder] = []
    for child in node.get("children", []):
        if not isinstance(child, dict):
            continue
        child_name = str(child.get("name", ""))
        if child.get("type") == "url":
            bookmarks.append(
                Bookmark(
                    url=str(child.get("url", "")),
                    title=child_name,
                    add_date=_chrome_date_to_epoch(child.get("date_added")),
                    source_path=path,
                    guid=_optional_str(child.get("guid")),
                )
            )
        elif child.get("type") == "folder":
            subfolders.append(
                _node_to_folder(child, path.child(child_name), child_name)
            )
    return Folder(
        name=name,
        subfolders=tuple(subfolders),
        bookmarks=tuple(bookmarks),
        add_date=_chrome_date_to_epoch(node.get("date_added")),
    )


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def parse_chrome_json(text: str) -> BookmarkTree:
    """Parse the Chrome ``Bookmarks`` JSON file into a BookmarkTree."""
    data = json.loads(text)
    roots_obj = data.get("roots", {}) if isinstance(data, dict) else {}
    roots: list[tuple[RootName, Folder]] = []
    for key, root_name in _ROOT_KEYS:
        node = roots_obj.get(key)
        if not isinstance(node, dict):
            continue
        base = FolderPath((root_name,))
        roots.append((root_name, _node_to_folder(node, base, root_name)))
    return BookmarkTree(roots=tuple(roots))


class ChromeJsonSource:
    """BookmarkSource reading Chrome's ``Bookmarks`` JSON (read-only)."""

    def load(self, path: Path) -> BookmarkTree:
        """Read and parse the profile ``Bookmarks`` file. Never writes it."""
        return parse_chrome_json(path.read_text(encoding="utf-8"))
