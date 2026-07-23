"""The ``BookmarkSink`` port: anything that serializes a BookmarkTree out."""

from __future__ import annotations

from typing import Protocol

from orgmarks.domain.model import BookmarkTree


class BookmarkSink(Protocol):
    """Serialize a BookmarkTree to text (Netscape HTML in v1)."""

    def emit(self, tree: BookmarkTree) -> str:
        """Return the serialized form of ``tree``."""
        ...
