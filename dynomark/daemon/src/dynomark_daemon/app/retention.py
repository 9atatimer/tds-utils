"""Use case: the store is swept for what it no longer keeps (DYNOMARK.DESIGN.md,
Key Decisions: Retention 2026-10-16; issue #421).

Clock-driven: the job loop runs ``enforce_retention`` on its own cadence.
The trees it reads are every known profile's latest: the writer's latest
tree and each reader-served profile's tree (issue #421); a host with none
tracks no entry. A reader-served profile's tree is forgotten once it is
``keep_ms`` old, so a profile not heard from for the window (an abandoned
browser profile, the old one after a reinstall) stops being known, and an
entry's jobs from a profile that is not known keep nothing (issue #534 T4).

What undo reads, and so what retention must keep: the latest tree snapshot
(the undo guard runs against it), the batch row and its receipt (the
operations and the node ids they minted), and the folder flags. No undo,
and no receipt, reads an archived snapshot (``snapshot_id`` is the batch's
fallback export, read by nothing in the daemon), so an archive goes once it
is ``keep_ms`` old whatever its batch, and the batch row stays naming none.

Each dropped entry is its own unit of work, so a sweep never holds the
store from the socket for the whole corpus.
"""

from dataclasses import dataclass

from dynomark_daemon.app.diffs import is_answered_request
from dynomark_daemon.domain.bookmark import Identity
from dynomark_daemon.domain.ids import RequestId, SnapshotId
from dynomark_daemon.domain.job import Job
from dynomark_daemon.domain.retention import (
    RETENTION_MS,
    is_tracked,
    plan_absences,
    present_in_any,
)
from dynomark_daemon.domain.tree import Snapshot
from dynomark_daemon.ports.clock import Clock
from dynomark_daemon.ports.store import CorpusStorePort


@dataclass(frozen=True, slots=True)
class Retained:
    """What one sweep dropped."""

    entries: tuple[Identity, ...]
    snapshots: tuple[SnapshotId, ...]
    requests: tuple[RequestId, ...]


def _jobs_by_identity(jobs: list[Job]) -> dict[Identity, list[Job]]:
    grouped: dict[Identity, list[Job]] = {}
    for job in jobs:
        grouped.setdefault(job.identity, []).append(job)
    return grouped


def _known_trees(*, store: CorpusStorePort) -> tuple[Snapshot, ...]:
    """Every tree of a known profile: each reader-served profile's tree not
    yet forgotten, and the writer's latest tree (which stands for the bound
    profile's, should it once have been served reader)."""
    by_profile = store.profile_trees()
    writer = store.writer_profile()
    if writer is not None:
        by_profile.pop(writer, None)
    latest = store.latest_tree_snapshot()
    trees = tuple(by_profile.values())
    return trees if latest is None else (*trees, latest)


def _sweep_entries(
    now: int, keep_ms: int, *, store: CorpusStorePort
) -> tuple[Identity, ...]:
    trees = _known_trees(store=store)
    jobs = _jobs_by_identity(store.list_jobs())
    tracked = frozenset(
        i for i in store.entry_identities() if is_tracked(jobs.get(i, []))
    )
    if not trees:
        # With no known tree nothing new can be judged absent, but an absence
        # already recorded keeps ageing: the tree that saw it gone may have
        # been forgotten since (Codex on 9atatimer/tds-utils PR#535).
        tracked = tracked & frozenset(store.absences())
    plan = plan_absences(
        tracked,
        present_in_any(trees),
        store.absences(),
        now=now,
        keep_ms=keep_ms,
    )
    for identity in plan.gone:
        store.put_absence(identity, now)
    for identity in plan.back:
        store.clear_absence(identity)
    for identity in plan.expired:
        store.drop_entry(identity)
    return plan.expired


def _forget_answered(*, store: CorpusStorePort) -> tuple[RequestId, ...]:
    answered = tuple(
        r for r in store.list_requests() if is_answered_request(r, store=store)
    )
    for request_id in answered:
        store.forget_request(request_id)
    return answered


def enforce_retention(
    *, store: CorpusStorePort, clock: Clock, keep_ms: int = RETENTION_MS
) -> Retained:
    """Track which entries' bookmarks left the tree, drop those gone for
    ``keep_ms`` with their saves and placement, drop archived snapshots
    taken more than ``keep_ms`` ago, and forget answered requests. Batch
    rows and jobs stay."""
    now = clock.now_ms()
    store.drop_profile_trees_before(now - keep_ms)
    entries = _sweep_entries(now, keep_ms, store=store)
    snapshots = tuple(store.drop_snapshots_before(now - keep_ms))
    return Retained(
        entries=entries, snapshots=snapshots, requests=_forget_answered(store=store)
    )
