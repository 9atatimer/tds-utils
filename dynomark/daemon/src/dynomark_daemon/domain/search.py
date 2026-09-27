"""Queries, hits, store candidates and the extension's local index."""

from collections.abc import Sequence
from dataclasses import dataclass
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
