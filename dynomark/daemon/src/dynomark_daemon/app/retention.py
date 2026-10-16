"""Use case: the store is swept for what it no longer keeps (DYNOMARK.DESIGN.md,
Key Decisions: Retention 2026-10-16; issue #421).

Clock-driven: the job loop runs ``enforce_retention`` on its own cadence.
Only the writer keeps tree snapshots, so a host with none tracks no entry.

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
    is_vouched_for,
    plan_absences,
    present_identities,
)
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


def _sweep_entries(
    now: int, keep_ms: int, *, store: CorpusStorePort
) -> tuple[Identity, ...]:
    tree = store.latest_tree_snapshot()
    writer = store.writer_profile()
    if tree is None or writer is None:
        return ()
    jobs = _jobs_by_identity(store.list_jobs())
    tracked = frozenset(
        i for i in store.entry_identities() if is_vouched_for(jobs.get(i, []), writer)
    )
    plan = plan_absences(
        tracked,
        present_identities(tree),
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
    entries = _sweep_entries(now, keep_ms, store=store)
    snapshots = tuple(store.drop_snapshots_before(now - keep_ms))
    return Retained(
        entries=entries, snapshots=snapshots, requests=_forget_answered(store=store)
    )
