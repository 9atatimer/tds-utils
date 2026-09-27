"""Queries, hits, store candidates and the extension's local index."""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Final

from dynomark_daemon.domain.bookmark import Identity
from dynomark_daemon.domain.tree import FolderPath


@dataclass(frozen=True, slots=True)
class Query:
    text: str


class HitTier(StrEnum):
    LOCAL = "local"
    CORPUS = "corpus"


@dataclass(frozen=True, slots=True)
class Hit:
    """A ranked match; ``score`` is in [0, 1]."""

    identity: Identity
    title: str
    path: FolderPath
    score: float
    tier: HitTier


@dataclass(frozen=True, slots=True)
class Candidate:
    """One row of a store candidate list (full-text or KNN), best first."""

    identity: Identity
    score: float


# --- Hybrid ranking (Key Decisions: fusion in the domain) ---

RRF_K: Final = 60
"""Reciprocal-rank-fusion constant: how much a top rank outweighs the next."""


def _reciprocal_ranks(candidates: Sequence[Candidate]) -> dict[Identity, float]:
    ranks: dict[Identity, float] = {}
    for rank, candidate in enumerate(candidates, start=1):
        ranks.setdefault(candidate.identity, 1.0 / (RRF_K + rank))
    return ranks


def fuse(text: Sequence[Candidate], knn: Sequence[Candidate]) -> list[Candidate]:
    """One ranking from the full-text and nearest-neighbour lists, each best
    first: reciprocal rank fusion, scaled so that leading both lists scores 1.
    Only ranks count, so neither list's score scale dominates. Ties break by
    identity."""
    lists = (_reciprocal_ranks(text), _reciprocal_ranks(knn))
    best = 2.0 / (RRF_K + 1)
    fused = {
        identity: min(1.0, sum(ranks.get(identity, 0.0) for ranks in lists) / best)
        for identity in lists[0].keys() | lists[1].keys()
    }
    ranked = sorted(fused.items(), key=lambda item: (-item[1], item[0].value))
    return [Candidate(identity, score) for identity, score in ranked]


@dataclass(frozen=True, slots=True)
class LocalIndexRow:
    """Per entry: identity, title, path, tags, one-line summary."""

    identity: Identity
    title: str
    path: FolderPath
    tags: tuple[str, ...]
    summary: str


@dataclass(frozen=True, slots=True)
class LocalIndex:
    rows: tuple[LocalIndexRow, ...]


# --- Local index rows (Ubiquitous language: LocalIndex; contract v1, Size
# limits: LocalIndexRow) ---

MAX_ROW_BYTES: Final = 512
MAX_TAGS: Final = 32
MAX_TAG_LENGTH: Final = 64
MAX_SUMMARY_LENGTH: Final = 512
MAX_TITLE_LENGTH: Final = 4096


def row_bytes(row: LocalIndexRow) -> int:
    """The row's size as the contract measures it: the UTF-8 length of its
    compact JSON (no whitespace, non-ASCII unescaped)."""
    document = {
        "identity": row.identity.value,
        "title": row.title,
        "path": {"root": row.path.root.value, "names": list(row.path.names)},
        "tags": list(row.tags),
        "summary": row.summary,
    }
    text = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
    return len(text.encode("utf-8"))


def fits(row: LocalIndexRow) -> bool:
    return row_bytes(row) <= MAX_ROW_BYTES


def one_line(summary: str) -> str:
    lines = summary.splitlines()
    return lines[0].strip() if lines else ""


def _longest_prefix(text: str, fits_with: Callable[[str], bool]) -> str:
    """The longest prefix of ``text`` (by code point) that still fits."""
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if fits_with(text[:middle]):
            low = middle
        else:
            high = middle - 1
    return text[:low]


def index_row(
    identity: Identity,
    *,
    title: str,
    path: FolderPath,
    tags: Sequence[str],
    summary: str,
) -> LocalIndexRow | None:
    """The entry's ``LocalIndexRow`` within 512 bytes: the summary trimmed
    first, then tags dropped from the end, then the title trimmed; ``None``
    when even identity and path alone do not fit."""
    row = LocalIndexRow(
        identity=identity,
        title=title[:MAX_TITLE_LENGTH],
        path=path,
        tags=tuple(t[:MAX_TAG_LENGTH] for t in tags if t)[:MAX_TAGS],
        summary=one_line(summary)[:MAX_SUMMARY_LENGTH],
    )
    if fits(row):
        return row
    row = replace(
        row,
        summary=_longest_prefix(row.summary, lambda s: fits(replace(row, summary=s))),
    )
    while not fits(row) and row.tags:
        row = replace(row, tags=row.tags[:-1])
    if not fits(row):
        row = replace(
            row,
            title=_longest_prefix(row.title, lambda t: fits(replace(row, title=t))),
        )
    return row if fits(row) else None
