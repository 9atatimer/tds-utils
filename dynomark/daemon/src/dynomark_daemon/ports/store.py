"""Seam: the corpus store (SQLite with FTS5 + a vector index / in-memory fake).

Everything durable the daemon keeps: entries, the two candidate lists
hybrid search fuses, placements, jobs, batches, snapshots, feedback and
diffs. Orderings are part of the contract so the fake and the SQLite
adapter can run one suite (tests/contract/ports/test_store_contract.py).
"""

from collections.abc import Iterable, Sequence
from typing import Protocol

from dynomark_daemon.domain.batch import BatchRecord
from dynomark_daemon.domain.bookmark import CorpusEntry, Identity, Save
from dynomark_daemon.domain.diff import DiffItem, TreeDiff
from dynomark_daemon.domain.events import Event, PendingEvent
from dynomark_daemon.domain.ids import (
    BatchId,
    DiffId,
    EventId,
    ItemId,
    JobId,
    NodeId,
    ProfileId,
    SnapshotId,
)
from dynomark_daemon.domain.job import Job, JobState
from dynomark_daemon.domain.placement import MoveFeedback, Placement
from dynomark_daemon.domain.search import Candidate, Query
from dynomark_daemon.domain.tree import Snapshot


class CorpusStorePort(Protocol):
    # --- Entries ---

    def put_entry(self, entry: CorpusEntry) -> None:
        """Insert or replace the one entry of ``entry.identity``."""
        ...

    def get_entry(self, identity: Identity) -> CorpusEntry | None: ...

    def list_entries(
        self, *, after: Identity | None = None, limit: int
    ) -> list[CorpusEntry]:
        """Up to ``limit`` entries with identity > ``after``, by identity."""
        ...

    # --- Candidates for hybrid search (fusion is the domain's) ---

    def text_candidates(self, query: Query, *, limit: int) -> list[Candidate]:
        """Entries containing every word of ``query`` (case-insensitive) in
        their title, summary, tags or captured text; best first."""
        ...

    def knn_candidates(
        self, vector: Sequence[float], *, limit: int, placed_only: bool = False
    ) -> list[Candidate]:
        """Nearest entries by cosine similarity (the ``score``), nearest first;
        ``placed_only`` keeps entries that have a placement."""
        ...

    # --- Placements ---

    def put_placement(self, placement: Placement) -> None: ...

    def get_placement(self, identity: Identity) -> Placement | None: ...

    # --- Jobs ---

    def put_job(self, job: Job) -> None:
        """Insert or replace by ``job_id``."""
        ...

    def get_job(self, job_id: JobId) -> Job | None: ...

    def find_job(
        self, profile_id: ProfileId, node_id: NodeId, identity: Identity
    ) -> Job | None:
        """The job of one save: ingest's idempotency key."""
        ...

    def list_jobs(self, *, state: JobState | None = None) -> list[Job]:
        """Jobs in first-insertion order, optionally in one state."""
        ...

    def put_save(self, job_id: JobId, save: Save) -> None:
        """Insert or replace the save (bookmark and capture) a job processes."""
        ...

    def get_save(self, job_id: JobId) -> Save | None: ...

    # --- Batches ---

    def put_batch(self, record: BatchRecord) -> None:
        """Insert or replace by ``record.batch.batch_id``."""
        ...

    def get_batch(self, batch_id: BatchId) -> BatchRecord | None: ...

    def list_batches(self) -> list[BatchRecord]:
        """Newest ``created_at`` first; ties newest-inserted first."""
        ...

    # --- Snapshots ---

    def put_tree_snapshot(self, snapshot: Snapshot) -> None:
        """Keep ``snapshot`` as the latest tree unless one with a later
        ``taken_at`` is already kept (idempotency key: ``taken_at``)."""
        ...

    def latest_tree_snapshot(self) -> Snapshot | None: ...

    def put_snapshot(self, snapshot_id: SnapshotId, snapshot: Snapshot) -> None:
        """Archive a batch's fallback export; never the latest tree."""
        ...

    def get_snapshot(self, snapshot_id: SnapshotId) -> Snapshot | None: ...

    # --- Feedback ---

    def put_feedback(self, feedback: MoveFeedback) -> None:
        """Record once per ``feedback_id``."""
        ...

    def recent_feedback(self, *, limit: int) -> list[MoveFeedback]:
        """Newest ``observed_at`` first."""
        ...

    # --- Diffs ---

    def put_diff(self, diff: TreeDiff) -> None:
        """Insert or replace a diff with its items."""
        ...

    def get_diff(self, diff_id: DiffId) -> TreeDiff | None: ...

    def list_diffs(self) -> list[TreeDiff]:
        """Newest ``proposed_at`` first; ties newest-inserted first."""
        ...

    def put_diff_item(self, item: DiffItem) -> None:
        """Replace one item of an existing diff.

        Raises:
            NotFound: no diff ``item.diff_id`` holds ``item.item_id``.
        """
        ...

    def get_diff_item(self, item_id: ItemId) -> DiffItem | None: ...

    # --- Events: durable per profile until acknowledged ---

    def put_event(self, profile_id: ProfileId, event: Event) -> None:
        """Append ``event`` for ``profile_id``; a known ``event_id`` is a no-op."""
        ...

    def unacked_events(self, profile_id: ProfileId) -> list[PendingEvent]:
        """The profile's unacknowledged events, oldest first."""
        ...

    def mark_pushed(self, profile_id: ProfileId, event_ids: Iterable[EventId]) -> None:
        """Record that these events went out live; unknown ids are ignored."""
        ...

    def ack_events(self, profile_id: ProfileId, event_ids: Iterable[EventId]) -> None:
        """Acknowledge these events of the profile; unknown ids are ignored."""
        ...
