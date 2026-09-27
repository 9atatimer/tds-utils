"""Queries, hits, store candidates and the extension's local index."""

from dataclasses import dataclass
from enum import StrEnum

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
