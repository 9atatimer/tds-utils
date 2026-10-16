"""Retention: what the corpus store stops keeping, and when (DYNOMARK.DESIGN.md,
Key Decisions: Retention 2026-10-16; issue #421).

A corpus entry, its saves and its placement go once its bookmark has been
absent from the tree for ``RETENTION_MS``; archived snapshots go once that
old; batch rows stay; answered requests go. The rules here take values;
the sweep that applies them is ``app/retention.py``.
"""

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from typing import Final

from dynomark_daemon.domain.bookmark import Identity
from dynomark_daemon.domain.job import Job, JobState
from dynomark_daemon.domain.tree import NodeKind, Snapshot

RETENTION_MS: Final = 30 * 86_400_000
"""How long an entry outlives its bookmark, and an archived snapshot its
reading (the owner's ruling: 30 days)."""

SETTLED_STATES: Final = frozenset({JobState.FILED, JobState.INDEXED, JobState.FAILED})
"""Job states with no work left that reads the entry, save or placement."""


# --- Predicates ---


def is_tracked(jobs: Iterable[Job]) -> bool:
    """The known trees judge whether an entry's bookmark is gone once every
    job of its identity is settled: a job still running needs its records.
    A job's profile does not matter (issue #534 T4): a profile that is not
    known -- the old one after a reinstall and rebind, a reader that never
    sent a tree or has not for the retention window -- vouches for nothing,
    so its saves are judged by the trees that are known."""
    return all(j.state in SETTLED_STATES for j in jobs)


# --- Pure helpers ---


def present_identities(tree: Snapshot) -> frozenset[Identity]:
    """The identities of every bookmark in ``tree``."""
    return frozenset(
        Identity.from_url(node.url)
        for node in tree.nodes
        if node.kind is NodeKind.BOOKMARK and node.url is not None
    )


def present_in_any(trees: Iterable[Snapshot]) -> frozenset[Identity]:
    """The identities some known profile's latest tree holds: an entry is
    absent only when none of them holds its URL."""
    return frozenset().union(*(present_identities(tree) for tree in trees))


@dataclass(frozen=True, slots=True)
class AbsencePlan:
    """What one sweep changes: entries found gone (tracked from now), entries
    found back (no longer tracked), and entries gone long enough to drop."""

    gone: tuple[Identity, ...]
    back: tuple[Identity, ...]
    expired: tuple[Identity, ...]


def plan_absences(
    tracked: Collection[Identity],
    present: Collection[Identity],
    absent_since: Mapping[Identity, int],
    *,
    now: int,
    keep_ms: int,
) -> AbsencePlan:
    """The sweep over the ``tracked`` entries against the identities
    ``present`` in the latest tree. An identity with an absence that is no
    longer tracked (it got a running job, or a reader's save) is back too:
    the tree no longer vouches for its absence."""
    gone = tuple(i for i in tracked if i not in present and i not in absent_since)
    back = tuple(i for i in absent_since if i in present or i not in tracked)
    expired = tuple(
        i
        for i, since in absent_since.items()
        if i in tracked and i not in present and now - since >= keep_ms
    )
    return AbsencePlan(gone=gone, back=back, expired=expired)
