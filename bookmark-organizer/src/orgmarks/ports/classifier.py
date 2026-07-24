"""The ``Classifier`` port: the LLM seam.

Provider and model live in ``taxonomy.yml``, never here. Adapters format the
folder ``skeleton`` and the prompt; the domain only sees ``ClassifyResult``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from orgmarks.domain.model import Bookmark, FolderPath
from orgmarks.domain.taxonomy import Intent


@dataclass(frozen=True, slots=True)
class ClassifyResult:
    """One bookmark's classification: an intent ``folder`` and a ``ref``."""

    url: str
    folder: FolderPath
    ref: FolderPath
    confidence: float
    proposed_new_folder: str | None = None


class Classifier(Protocol):
    """Classify a batch of residue bookmarks into intent + reference homes."""

    def classify(
        self,
        batch: Sequence[Bookmark],
        *,
        intents: Sequence[Intent],
        skeleton: str,
    ) -> list[ClassifyResult]:
        """Return one ClassifyResult per bookmark in ``batch``."""
        ...
