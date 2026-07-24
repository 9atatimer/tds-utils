"""The ``BookmarkSource`` port: anything that reads a BookmarkTree in."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from orgmarks.domain.model import BookmarkTree


class BookmarkSource(Protocol):
    """Read a bookmark collection from a path into a BookmarkTree."""

    def load(self, path: Path) -> BookmarkTree:
        """Load and parse ``path`` into a BookmarkTree (read-only)."""
        ...
