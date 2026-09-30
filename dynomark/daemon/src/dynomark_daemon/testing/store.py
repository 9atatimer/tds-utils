"""An in-memory ``CorpusStorePort``: dicts in insertion order, no I/O.

Full-text candidates: an entry matches when every query word (``\\w+``,
lower-cased) occurs among the words of its title, summary, tags and
captured text; the score is the share of the entry's words that are query
words. KNN candidates: cosine similarity. Ties break by identity.

A unit of work copies every table on entry and puts the copies back when
it raises, so a test that kills a use case inside one (an exception from
the Nth write) sees what a crash before the commit would leave.
"""

import copy
import math
import re
from collections.abc import Collection, Iterable, Iterator, Sequence
from contextlib import contextmanager
from typing import Final

from dynomark_daemon.domain.batch import BatchRecord, BatchState
from dynomark_daemon.domain.bookmark import CorpusEntry, Identity, Save
from dynomark_daemon.domain.diff import DiffItem, TreeDiff
from dynomark_daemon.domain.events import Event, PendingEvent
from dynomark_daemon.domain.ids import (
    BatchId,
    DiffId,
    EventId,
    FeedbackId,
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
from dynomark_daemon.ports.errors import NotFound
from dynomark_daemon.ports.store import StoredEntry

WORD: Final = re.compile(r"\w+")
TABLES: Final = (
    "_entries",
    "_positions",
    "_placements",
    "_jobs",
    "_saves",
    "_batches",
    "_latest_tree",
    "_snapshots",
    "_feedback",
    "_diffs",
    "_events",
    "_flags",
    "_writer_profile",
    "_follow_ups",
    "_requests",
)
"""Every attribute holding stored state; a unit of work restores these."""


# --- Helpers ---


def _words(text: str) -> list[str]:
    return WORD.findall(text.lower())


def _entry_words(entry: CorpusEntry) -> list[str]:
    fields = [entry.bookmark.title, entry.summary, *entry.tags, entry.capture.text]
    return [word for field in fields for word in _words(field)]


def _text_score(query_words: set[str], entry: CorpusEntry) -> float | None:
    words = _entry_words(entry)
    if not query_words or not query_words <= set(words):
        return None
    return sum(word in query_words for word in words) / len(words)


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    norms = math.hypot(*a) * math.hypot(*b)
    if norms == 0.0 or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=True)) / norms


def _best_first(candidates: list[Candidate], limit: int) -> list[Candidate]:
    ranked = sorted(candidates, key=lambda c: (-c.score, c.identity.value))
    return ranked[:limit]


def _newest_first[T](rows: list[T], key: list[int]) -> list[T]:
    """Sort by ``key`` descending; equal keys newest-inserted first."""
    order = sorted(range(len(rows)), key=lambda i: (key[i], i), reverse=True)
    return [rows[i] for i in order]


def _oldest_first(rows: list[BatchRecord]) -> list[BatchRecord]:
    """By ``created_at``; equal times first-inserted first."""
    return sorted(rows, key=lambda r: r.created_at)


# --- The fake ---


class InMemoryCorpusStore:
    def __init__(self) -> None:
        self._entries: dict[Identity, CorpusEntry] = {}
        self._positions: dict[Identity, int] = {}
        self._placements: dict[Identity, Placement] = {}
        self._jobs: dict[JobId, Job] = {}
        self._saves: dict[JobId, Save] = {}
        self._batches: dict[BatchId, BatchRecord] = {}
        self._latest_tree: Snapshot | None = None
        self._snapshots: dict[SnapshotId, Snapshot] = {}
        self._feedback: dict[FeedbackId, MoveFeedback] = {}
        self._diffs: dict[DiffId, TreeDiff] = {}
        self._events: dict[ProfileId, dict[EventId, PendingEvent]] = {}
        self._flags: dict[NodeId, FolderFlags] = {}
        self._writer_profile: ProfileId | None = None
        self._follow_ups: dict[ProfileId, FolderPath] = {}
        self._requests: dict[RequestId, str] = {}

    # --- Units of work ---

    @contextmanager
    def atomic(self) -> Iterator[None]:
        saved = {name: copy.copy(getattr(self, name)) for name in TABLES}
        saved["_events"] = {p: dict(e) for p, e in self._events.items()}
        try:
            yield
        except BaseException:
            for name, value in saved.items():
                setattr(self, name, value)
            raise

    # --- Entries ---

    def put_entry(self, entry: CorpusEntry) -> None:
        self._positions.setdefault(entry.identity, len(self._positions) + 1)
        self._entries[entry.identity] = entry

    def get_entry(self, identity: Identity) -> CorpusEntry | None:
        return self._entries.get(identity)

    def list_entries(
        self, *, after: int | None = None, limit: int
    ) -> list[StoredEntry]:
        stored = (
            StoredEntry(self._positions[identity], entry)
            for identity, entry in self._entries.items()
        )
        ordered = sorted(stored, key=lambda s: s.position)
        return [s for s in ordered if after is None or s.position > after][:limit]

    # --- Candidates ---

    def text_candidates(self, query: Query, *, limit: int) -> list[Candidate]:
        query_words = set(_words(query.text))
        scored = [
            (entry.identity, _text_score(query_words, entry))
            for entry in self._entries.values()
        ]
        return _best_first(
            [Candidate(identity, score) for identity, score in scored if score],
            limit,
        )

    def knn_candidates(
        self, vector: Sequence[float], *, limit: int, placed_only: bool = False
    ) -> list[Candidate]:
        return _best_first(
            [
                Candidate(entry.identity, _cosine(vector, entry.embedding.vector))
                for entry in self._entries.values()
                if not placed_only or entry.identity in self._placements
            ],
            limit,
        )

    # --- Placements ---

    def put_placement(self, placement: Placement) -> None:
        self._placements[placement.identity] = placement

    def get_placement(self, identity: Identity) -> Placement | None:
        return self._placements.get(identity)

    # --- Jobs ---

    def put_job(self, job: Job) -> None:
        self._jobs[job.job_id] = job

    def get_job(self, job_id: JobId) -> Job | None:
        return self._jobs.get(job_id)

    def find_job(
        self, profile_id: ProfileId, node_id: NodeId, identity: Identity
    ) -> Job | None:
        key = (profile_id, node_id, identity)
        return next(
            (
                j
                for j in self._jobs.values()
                if (j.profile_id, j.node_id, j.identity) == key
            ),
            None,
        )

    def list_jobs(self, *, state: JobState | None = None) -> list[Job]:
        return [j for j in self._jobs.values() if state is None or j.state == state]

    def list_jobs_in(self, states: Collection[JobState]) -> list[Job]:
        return [j for j in self._jobs.values() if j.state in states]

    def put_save(self, job_id: JobId, save: Save) -> None:
        self._saves[job_id] = save

    def get_save(self, job_id: JobId) -> Save | None:
        return self._saves.get(job_id)

    # --- Batches ---

    def put_batch(self, record: BatchRecord) -> None:
        self._batches[record.batch.batch_id] = record

    def get_batch(self, batch_id: BatchId) -> BatchRecord | None:
        return self._batches.get(batch_id)

    def list_batches(self) -> list[BatchRecord]:
        rows = list(self._batches.values())
        return _newest_first(rows, [r.created_at for r in rows])

    def batches_awaiting_tree(self) -> list[BatchRecord]:
        return _oldest_first(
            [
                r
                for r in self._batches.values()
                if r.receipt is not None and not r.tree_since_receipt
            ]
        )

    def batches_in_state(
        self, profile_id: ProfileId, state: BatchState
    ) -> list[BatchRecord]:
        return _oldest_first(
            [
                r
                for r in self._batches.values()
                if r.profile_id == profile_id and r.state is state
            ]
        )

    # --- Snapshots ---

    def put_tree_snapshot(self, snapshot: Snapshot) -> None:
        latest = self._latest_tree
        if latest is None or snapshot.taken_at >= latest.taken_at:
            self._latest_tree = snapshot

    def latest_tree_snapshot(self) -> Snapshot | None:
        return self._latest_tree

    def put_snapshot(self, snapshot_id: SnapshotId, snapshot: Snapshot) -> None:
        self._snapshots[snapshot_id] = snapshot

    def get_snapshot(self, snapshot_id: SnapshotId) -> Snapshot | None:
        return self._snapshots.get(snapshot_id)

    def release_snapshot(self, snapshot_id: SnapshotId) -> None:
        if all(r.snapshot_id != snapshot_id for r in self._batches.values()):
            self._snapshots.pop(snapshot_id, None)

    # --- Feedback ---

    def put_feedback(self, feedback: MoveFeedback) -> None:
        self._feedback.setdefault(feedback.feedback_id, feedback)

    def recent_feedback(self, *, limit: int) -> list[MoveFeedback]:
        rows = list(self._feedback.values())
        return _newest_first(rows, [f.observed_at for f in rows])[:limit]

    # --- Diffs ---

    def put_diff(self, diff: TreeDiff) -> None:
        self._diffs[diff.diff_id] = diff

    def get_diff(self, diff_id: DiffId) -> TreeDiff | None:
        return self._diffs.get(diff_id)

    def list_diffs(self) -> list[TreeDiff]:
        rows = list(self._diffs.values())
        return _newest_first(rows, [d.proposed_at for d in rows])

    def put_diff_item(self, item: DiffItem) -> None:
        diff = self._diffs.get(item.diff_id)
        if diff is None or item.item_id not in {i.item_id for i in diff.items}:
            raise NotFound(f"no diff {item.diff_id} holds item {item.item_id}")
        items = tuple(item if i.item_id == item.item_id else i for i in diff.items)
        self._diffs[diff.diff_id] = TreeDiff(
            diff_id=diff.diff_id,
            kind=diff.kind,
            proposed_at=diff.proposed_at,
            items=items,
        )

    def get_diff_item(self, item_id: ItemId) -> DiffItem | None:
        items = (i for d in self._diffs.values() for i in d.items)
        return next((i for i in items if i.item_id == item_id), None)

    # --- Events ---

    def put_event(self, profile_id: ProfileId, event: Event) -> None:
        events = self._events.setdefault(profile_id, {})
        events.setdefault(event.event_id, PendingEvent(event, pushed=False))

    def unacked_events(self, profile_id: ProfileId) -> list[PendingEvent]:
        return list(self._events.get(profile_id, {}).values())

    def mark_pushed(self, profile_id: ProfileId, event_ids: Iterable[EventId]) -> None:
        events = self._events.get(profile_id, {})
        for event_id in event_ids:
            if event_id in events:
                events[event_id] = PendingEvent(events[event_id].event, pushed=True)

    def ack_events(self, profile_id: ProfileId, event_ids: Iterable[EventId]) -> None:
        events = self._events.get(profile_id, {})
        for event_id in event_ids:
            events.pop(event_id, None)

    # --- Owned-folder flags ---

    def put_folder_flags(self, node_id: NodeId, flags: FolderFlags) -> None:
        self._flags[node_id] = flags

    def folder_flags(self) -> dict[NodeId, FolderFlags]:
        return dict(self._flags)

    # --- Profiles ---

    def writer_profile(self) -> ProfileId | None:
        return self._writer_profile

    def bind_writer_profile(self, profile_id: ProfileId) -> None:
        if self._writer_profile is None:
            self._writer_profile = profile_id

    def put_follow_up(self, profile_id: ProfileId, path: FolderPath) -> None:
        self._follow_ups[profile_id] = path

    def follow_up_of(self, profile_id: ProfileId) -> FolderPath | None:
        return self._follow_ups.get(profile_id)

    # --- Request-id memory ---

    def put_request(self, request_id: RequestId, fingerprint: str) -> None:
        self._requests[request_id] = fingerprint

    def get_request(self, request_id: RequestId) -> str | None:
        return self._requests.get(request_id)
