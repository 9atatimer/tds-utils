"""CorpusStorePort contract: one suite, every implementation.

STORES names each implementation by a factory taking a per-test temporary
directory; the in-memory fake is here now, and the SQLite adapter
(task-025) registers beside it and must pass the same tests unchanged.

Design: Data Model ("one corpus_entry per identity"), Seams ("Corpus
store ... SQLite with FTS5 and a vector extension / in-memory fake"), Key
Decisions ("Hybrid ranking: fusion in the domain over the store's two
candidate lists"); contract/v1/README.md, Delivery and replay
("index.pull cursors ... keyset by identity") and the idempotency table.
"""

from collections.abc import Callable
from pathlib import Path

import pytest

from dynomark_daemon.domain.batch import BatchState
from dynomark_daemon.domain.bookmark import Identity, Save
from dynomark_daemon.domain.events import JobUpdated, PendingEvent
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
from dynomark_daemon.domain.job import JobState
from dynomark_daemon.domain.search import Query
from dynomark_daemon.domain.tree import FolderFlags
from dynomark_daemon.ports.errors import NotFound
from dynomark_daemon.ports.store import CorpusStorePort
from dynomark_daemon.testing.store import InMemoryCorpusStore
from tests._factories import (
    make_batch,
    make_bookmark,
    make_capture,
    make_diff,
    make_diff_item,
    make_entry,
    make_feedback,
    make_job,
    make_path,
    make_placement,
    make_snapshot,
)

pytestmark = pytest.mark.contract

PROFILE_A, PROFILE_B = ProfileId("profile-a"), ProfileId("profile-b")

STORES: dict[str, Callable[[Path], CorpusStorePort]] = {
    "memory": lambda _tmp: InMemoryCorpusStore(),
}


@pytest.fixture(params=sorted(STORES))
def store(request: pytest.FixtureRequest, tmp_path: Path) -> CorpusStorePort:
    return STORES[request.param](tmp_path)


# --- Entries ---


def test_get_entry_returns_the_entry_put(store: CorpusStorePort) -> None:
    """Given a stored entry, When read by identity, Then it is the same value."""
    entry = make_entry(summary="a runtime", tags=("rust",), text="Tokio text")
    store.put_entry(entry)

    assert store.get_entry(entry.identity) == entry


def test_get_entry_of_unknown_identity_is_none(store: CorpusStorePort) -> None:
    """Given an empty store, When an identity is read, Then there is no entry."""
    assert store.get_entry(Identity("https://unknown.example/")) is None


def test_put_entry_twice_keeps_one_entry_per_identity(store: CorpusStorePort) -> None:
    """Given an entry, When another with the same identity is put, Then it
    replaces the first (one corpus_entry per identity)."""
    store.put_entry(make_entry(summary="old"))
    store.put_entry(newer := make_entry(summary="new"))

    assert store.list_entries(limit=10) == [newer]


def test_list_entries_pages_by_identity_keyset(store: CorpusStorePort) -> None:
    """Given entries put out of order, When listed in pages of two after the last
    identity seen, Then every entry comes once, ordered by identity."""
    urls = ["https://c.example/", "https://a.example/", "https://b.example/"]
    for url in urls:
        store.put_entry(make_entry(url))

    first = store.list_entries(limit=2)
    rest = store.list_entries(after=first[-1].identity, limit=2)

    assert [e.identity.value for e in first + rest] == sorted(urls)


# --- Placements ---


def test_get_placement_returns_the_latest_put(store: CorpusStorePort) -> None:
    """Given a placement replaced by another for the same identity, When read,
    Then the latest is returned; an unplaced identity has none."""
    store.put_placement(make_placement(folder=make_path("Dynomark", "Rust")))
    store.put_placement(latest := make_placement(folder=make_path("Dynomark", "Go")))

    assert store.get_placement(latest.identity) == latest
    assert store.get_placement(Identity("https://unplaced.example/")) is None


# --- Candidates for hybrid search ---


def _found(store: CorpusStorePort, text: str) -> list[str]:
    return [c.identity.value for c in store.text_candidates(Query(text), limit=5)]


def test_text_candidates_find_a_word_only_in_captured_text(
    store: CorpusStorePort,
) -> None:
    """Given an entry whose captured text alone holds a word, When that word is
    queried, Then the entry is a candidate (Goal 4: an entry whose only match
    is in captured page text)."""
    store.put_entry(make_entry("https://a.example/", text="about select cancellation"))
    store.put_entry(make_entry("https://b.example/", text="about gardening"))

    found = store.text_candidates(Query("cancellation"), limit=10)

    assert [c.identity.value for c in found] == ["https://a.example/"]


def test_text_candidates_match_title_summary_and_tags_case_insensitively(
    store: CorpusStorePort,
) -> None:
    """Given words in a title, a summary and a tag, When queried in another case,
    Then each entry is found."""
    store.put_entry(make_entry("https://t.example/", title="Tokio Tutorial"))
    store.put_entry(
        make_entry("https://s.example/", title="S", summary="an async runtime")
    )
    store.put_entry(make_entry("https://g.example/", title="G", tags=("concurrency",)))

    assert _found(store, "TUTORIAL") == ["https://t.example/"]
    assert _found(store, "Runtime") == ["https://s.example/"]
    assert _found(store, "Concurrency") == ["https://g.example/"]


def test_text_candidates_require_every_query_word(store: CorpusStorePort) -> None:
    """Given entries holding one or both of two words, When both are queried,
    Then only the entry holding both is a candidate."""
    store.put_entry(make_entry("https://both.example/", text="rust async"))
    store.put_entry(make_entry("https://one.example/", text="rust only"))

    found = store.text_candidates(Query("async rust"), limit=10)

    assert [c.identity.value for c in found] == ["https://both.example/"]


def test_text_candidates_are_best_first_and_limited(store: CorpusStorePort) -> None:
    """Given more matches than the limit, When queried, Then at most limit come
    back with non-increasing scores."""
    for i in range(5):
        store.put_entry(make_entry(f"https://{i}.example/", text="rust " * (i + 1)))

    found = store.text_candidates(Query("rust"), limit=3)

    assert len(found) == 3
    assert [c.score for c in found] == sorted((c.score for c in found), reverse=True)


def test_knn_candidates_are_nearest_first_and_limited(store: CorpusStorePort) -> None:
    """Given entries at known angles, When the nearest two to a vector are asked
    for, Then they come nearest first with cosine similarity as the score."""
    store.put_entry(make_entry("https://same.example/", vector=(1.0, 0.0)))
    store.put_entry(make_entry("https://near.example/", vector=(0.8, 0.6)))
    store.put_entry(make_entry("https://far.example/", vector=(0.0, 1.0)))

    found = store.knn_candidates((1.0, 0.0), limit=2)

    assert [c.identity.value for c in found] == [
        "https://same.example/",
        "https://near.example/",
    ]
    assert [round(c.score, 6) for c in found] == [1.0, 0.8]


def test_knn_candidates_placed_only_skips_unplaced_entries(
    store: CorpusStorePort,
) -> None:
    """Given a placed and an unplaced entry, When neighbours are asked for among
    placed entries only, Then the unplaced one is left out (placement uses
    already-placed neighbours)."""
    store.put_entry(make_entry("https://placed.example/", vector=(0.6, 0.8)))
    store.put_entry(make_entry("https://loose.example/", vector=(1.0, 0.0)))
    store.put_placement(make_placement("https://placed.example/"))

    found = store.knn_candidates((1.0, 0.0), limit=5, placed_only=True)

    assert [c.identity.value for c in found] == ["https://placed.example/"]


# --- Jobs ---


def test_find_job_by_profile_node_and_identity(store: CorpusStorePort) -> None:
    """Given a job, When found by its (profile, node id, identity), Then it is
    that job; another profile's key finds nothing (ingest's idempotency key)."""
    job = make_job(profile_id="profile-a", node_id="42")
    store.put_job(job)

    assert store.find_job(ProfileId("profile-a"), NodeId("42"), job.identity) == job
    assert store.find_job(ProfileId("profile-b"), NodeId("42"), job.identity) is None


def test_put_job_replaces_by_job_id_and_list_filters_by_state(
    store: CorpusStorePort,
) -> None:
    """Given two jobs, one later moved to FAILED, When listed, Then both appear
    in first-insertion order and the FAILED filter returns only the one."""
    store.put_job(make_job("job-2", node_id="2"))
    store.put_job(make_job("job-1", node_id="1"))
    store.put_job(failed := make_job("job-2", node_id="2", state=JobState.FAILED))

    assert [j.job_id for j in store.list_jobs()] == ["job-2", "job-1"]
    assert store.list_jobs(state=JobState.FAILED) == [failed]
    assert store.get_job(JobId("job-2")) == failed
    assert store.get_job(JobId("job-9")) is None


def test_get_save_returns_the_save_ingested_with_the_job(
    store: CorpusStorePort,
) -> None:
    """Given a job's save (bookmark and capture) is put, When read by job id,
    Then it is the same value; an unknown job has none (Durable jobs:
    persisted before acknowledgement)."""
    save = Save(bookmark=make_bookmark(), capture=make_capture("Tokio text"))
    store.put_save(JobId("job-1"), save)

    assert store.get_save(JobId("job-1")) == save
    assert store.get_save(JobId("job-2")) is None


# --- Batches ---


def test_put_batch_replaces_by_batch_id(store: CorpusStorePort) -> None:
    """Given a PROPOSED batch, When stored again APPLIED, Then reading it gives the
    APPLIED record; an unknown batch id gives none."""
    store.put_batch(make_batch("batch-1"))
    store.put_batch(applied := make_batch("batch-1", state=BatchState.APPLIED))

    assert store.get_batch(BatchId("batch-1")) == applied
    assert store.get_batch(BatchId("batch-9")) is None


def test_list_batches_is_newest_first(store: CorpusStorePort) -> None:
    """Given batches created at different times, When listed, Then the newest
    comes first; equal times put the later-inserted first."""
    store.put_batch(make_batch("old", created_at=1))
    store.put_batch(make_batch("new", created_at=3))
    store.put_batch(make_batch("tie-a", created_at=2))
    store.put_batch(make_batch("tie-b", created_at=2))

    listed = [r.batch.batch_id for r in store.list_batches()]

    assert listed == ["new", "tie-b", "tie-a", "old"]


# --- Snapshots ---


def test_latest_tree_snapshot_keeps_the_latest_taken_at(
    store: CorpusStorePort,
) -> None:
    """Given a newer tree snapshot then an older one arriving late, When the latest
    is read, Then it is the newer (the idempotency key is taken_at)."""
    store.put_tree_snapshot(newer := make_snapshot(taken_at=20, title="new"))
    store.put_tree_snapshot(make_snapshot(taken_at=10, title="old"))

    assert store.latest_tree_snapshot() == newer


def test_archived_snapshot_never_replaces_the_latest_tree(
    store: CorpusStorePort,
) -> None:
    """Given a tree snapshot, When a receipt's snapshot is archived with a later
    taken_at, Then it is readable by id and the latest tree is unchanged."""
    store.put_tree_snapshot(tree := make_snapshot(taken_at=10))
    store.put_snapshot(SnapshotId("snap-1"), receipt := make_snapshot(taken_at=99))

    assert store.get_snapshot(SnapshotId("snap-1")) == receipt
    assert store.latest_tree_snapshot() == tree
    assert store.get_snapshot(SnapshotId("snap-9")) is None


def test_latest_tree_snapshot_of_an_empty_store_is_none(
    store: CorpusStorePort,
) -> None:
    """Given no snapshot, When the latest tree is read, Then there is none."""
    assert store.latest_tree_snapshot() is None


# --- Feedback ---


def test_recent_feedback_is_newest_first_and_recorded_once(
    store: CorpusStorePort,
) -> None:
    """Given feedback recorded twice under one id and another newer one, When the
    most recent are read, Then each appears once, newest first."""
    store.put_feedback(older := make_feedback("fb-1", observed_at=10))
    store.put_feedback(make_feedback("fb-1", observed_at=10))
    store.put_feedback(newer := make_feedback("fb-2", observed_at=20))

    assert store.recent_feedback(limit=5) == [newer, older]
    assert store.recent_feedback(limit=1) == [newer]


# --- Diffs ---


def test_put_diff_item_records_acceptance_inside_its_diff(
    store: CorpusStorePort,
) -> None:
    """Given a stored diff, When one item is replaced by its accepted version,
    Then both the item and the diff read back show the acceptance."""
    store.put_diff(make_diff("diff-1"))
    accepted = make_diff_item("item-1", diff_id="diff-1", accepted_at=1_790_000_006_000)

    store.put_diff_item(accepted)

    assert store.get_diff_item(ItemId("item-1")) == accepted
    diff = store.get_diff(DiffId("diff-1"))
    assert diff is not None and diff.items == (accepted,)


def test_put_diff_item_of_an_unknown_item_raises_not_found(
    store: CorpusStorePort,
) -> None:
    """Given no diff holding the item, When the item is put, Then NotFound is
    raised and nothing is stored."""
    with pytest.raises(NotFound):
        store.put_diff_item(make_diff_item("item-9", diff_id="diff-9"))

    assert store.get_diff_item(ItemId("item-9")) is None


def test_list_diffs_is_newest_first(store: CorpusStorePort) -> None:
    """Given diffs proposed at different times, When listed, Then newest first;
    an unknown diff id reads as none."""
    store.put_diff(make_diff("old", proposed_at=1))
    store.put_diff(make_diff("new", proposed_at=2))

    assert [d.diff_id for d in store.list_diffs()] == ["new", "old"]
    assert store.get_diff(DiffId("diff-9")) is None


# --- Events (contract/v1 README, Delivery and replay) ---


def _job_event(event_id: str) -> JobUpdated:
    return JobUpdated(event_id=EventId(event_id), job=make_job())


def test_unacked_events_are_oldest_first_until_acknowledged(
    store: CorpusStorePort,
) -> None:
    """Given events put for a profile, When one is acknowledged, Then the rest
    stay, oldest first; unknown and repeated acks change nothing."""
    first, second = _job_event("evt-1"), _job_event("evt-2")
    store.put_event(PROFILE_A, first)
    store.put_event(PROFILE_A, second)

    store.ack_events(PROFILE_A, [EventId("evt-1"), EventId("evt-9")])
    store.ack_events(PROFILE_A, [EventId("evt-1")])

    assert [p.event for p in store.unacked_events(PROFILE_A)] == [second]


def test_events_belong_to_their_profile(store: CorpusStorePort) -> None:
    """Given an event of one profile, When another profile reads or acks, Then
    it neither sees nor acknowledges it."""
    event = _job_event("evt-1")
    store.put_event(PROFILE_A, event)

    store.ack_events(PROFILE_B, [EventId("evt-1")])

    assert store.unacked_events(PROFILE_B) == []
    assert [p.event for p in store.unacked_events(PROFILE_A)] == [event]


def test_put_event_twice_keeps_one_and_marks_pushed(store: CorpusStorePort) -> None:
    """Given an event put twice, When it is marked pushed, Then it is held once
    and reads back as pushed until acknowledged."""
    event = _job_event("evt-1")
    store.put_event(PROFILE_A, event)
    store.put_event(PROFILE_A, event)
    assert store.unacked_events(PROFILE_A) == [PendingEvent(event, pushed=False)]

    store.mark_pushed(PROFILE_A, [EventId("evt-1")])

    assert store.unacked_events(PROFILE_A) == [PendingEvent(event, pushed=True)]


# --- Owned-folder flags (Data Model: owned_folder pinned, locked) ---


def test_folder_flags_are_kept_per_node_and_replaced(store: CorpusStorePort) -> None:
    """Given flags set on two folders and one set again, When read, Then each
    folder holds its latest flags."""
    store.put_folder_flags(NodeId("14"), FolderFlags(pinned=True, locked=False))
    store.put_folder_flags(NodeId("21"), FolderFlags(pinned=False, locked=True))
    store.put_folder_flags(NodeId("14"), FolderFlags(pinned=False, locked=True))

    assert store.folder_flags() == {
        NodeId("14"): FolderFlags(pinned=False, locked=True),
        NodeId("21"): FolderFlags(pinned=False, locked=True),
    }
