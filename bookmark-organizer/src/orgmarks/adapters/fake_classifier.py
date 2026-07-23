"""A deterministic in-memory Classifier for tests and pipeline wiring.

No network, no sleep. Configured with an explicit URL -> result table (or a
callable); any URL not covered falls back to a low-confidence result so the
pipeline routes it to ``_triage``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from orgmarks.domain.model import Bookmark, FolderPath
from orgmarks.domain.taxonomy import Intent
from orgmarks.ports.classifier import ClassifyResult

_DEFAULT_FALLBACK = ClassifyResult(
    url="",
    folder=FolderPath.from_string("work"),
    ref=FolderPath.from_string("uncategorized"),
    confidence=0.0,
)


class FakeClassifier:
    """Classifier fake driven by a table or a callable."""

    def __init__(
        self,
        table: Mapping[str, ClassifyResult] | None = None,
        *,
        default: Callable[[Bookmark], ClassifyResult] | None = None,
    ) -> None:
        """Build a fake from a URL->result ``table`` and/or a ``default`` fn."""
        self._table = dict(table or {})
        self._default = default

    def _resolve(self, bookmark: Bookmark) -> ClassifyResult:
        hit = self._table.get(bookmark.url)
        if hit is not None:
            return hit
        if self._default is not None:
            return self._default(bookmark)
        return ClassifyResult(
            url=bookmark.url,
            folder=_DEFAULT_FALLBACK.folder,
            ref=_DEFAULT_FALLBACK.ref,
            confidence=_DEFAULT_FALLBACK.confidence,
        )

    def classify(
        self,
        batch: Sequence[Bookmark],
        *,
        intents: Sequence[Intent],
        skeleton: str,
    ) -> list[ClassifyResult]:
        """Return one deterministic ClassifyResult per bookmark in ``batch``."""
        return [self._resolve(bm) for bm in batch]
