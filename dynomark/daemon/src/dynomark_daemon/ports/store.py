"""Seam: the corpus store (SQLite with FTS5 + a vector index / in-memory fake).

Everything durable the daemon keeps: entries, the two candidate lists
hybrid search fuses, placements, jobs, batches, snapshots, feedback and
diffs. Orderings are part of the contract so the fake and the SQLite
adapter can run one suite (tests/contract/ports/test_store_contract.py).

Each write is durable on its own. A use case that makes several writes
whose partial completion would be observable after a crash makes them in
one ``atomic()`` unit of work, so a crash between two of them loses both.
"""

from collections.abc import Iterable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
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
    RequestId,
    SnapshotId,
)
from dynomark_daemon.domain.job import Job, JobState
from dynomark_daemon.domain.placement import MoveFeedback, Placement
from dynomark_daemon.domain.search import Candidate, Query
from dynomark_daemon.domain.tree import FolderFlags, FolderPath, Snapshot


@dataclass(frozen=True, slots=True)
class StoredEntry:
    """An entry and its store position: assigned on first put, kept when the
    entry is replaced, increasing with every new identity. Pages of entries
    are keyset by it, so a page boundary survives any change to the corpus."""

    position: int
    entry: CorpusEntry


class CorpusStorePort(Protocol):
    # --- Units of work ---

    def atomic(self) -> AbstractContextManager[None]:
        """A unit of work: the writes made inside commit together when the
        block completes, and none of them does when it raises (a crash
        before it completes is the same). A unit opened inside another
        commits only with the outermost one; one that raises undoes only
        its own writes. Reads inside see the unit's writes. No other
        caller writes while a unit is open, so a unit holds no I/O but the
        store's: never a model, fetch or transport call.
        """
        ...

    # --- Entries ---

    def put_entry(self, entry: CorpusEntry) -> None:
        """Insert or replace the one entry of ``entry.identity``."""
        ...

    def get_entry(self, identity: Identity) -> CorpusEntry | None: ...

    def list_entries(
        self, *, after: int | None = None, limit: int
    ) -> list[StoredEntry]:
        """Up to ``limit`` entries with position > ``after``, by position."""
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

    # --- Owned-folder flags ---

    def put_folder_flags(self, node_id: NodeId, flags: FolderFlags) -> None:
        """Set the flags of an owned folder (by this host's node id)."""
        ...

    def folder_flags(self) -> dict[NodeId, FolderFlags]: ...

    # --- Profiles ---

    def writer_profile(self) -> ProfileId | None:
        """The profile this store files for, once bound."""
        ...

    def bind_writer_profile(self, profile_id: ProfileId) -> None:
        """Bind the store to ``profile_id`` unless it is already bound."""
        ...

    def put_follow_up(self, profile_id: ProfileId, path: FolderPath) -> None:
        """Keep the ``Follow Up`` folder the profile's extension resolved."""
        ...

    def follow_up_of(self, profile_id: ProfileId) -> FolderPath | None: ...

    # --- Request-id memory ---

    def put_request(self, request_id: RequestId, fingerprint: str) -> None:
        """Remember the body fingerprint a request id arrived with."""
        ...

    def get_request(self, request_id: RequestId) -> str | None: ...
