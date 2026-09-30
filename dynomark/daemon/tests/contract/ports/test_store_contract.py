"""CorpusStorePort contract: one suite, every implementation.

STORES names each implementation by a factory taking a per-test temporary
directory: the in-memory fake, and the SQLite adapter (task-025), which
runs the same tests unchanged against a temp-file database and so carries
the ``integration`` marker as well.

Design: Data Model ("one corpus_entry per identity"), Seams ("Corpus
store ... SQLite with FTS5 and a vector extension / in-memory fake"), Key
Decisions ("Hybrid ranking: fusion in the domain over the store's two
candidate lists"); contract/v1/README.md, Delivery and replay
("index.pull cursors MUST stay valid across data changes") and the
idempotency table. Entries page by their store position, a compact keyset
that fits the 1,024-byte ``Cursor`` where an identity (up to 65,536 code
points) does not.
"""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from dynomark_daemon.adapters.sqlite_store import SqliteCorpusStore
from dynomark_daemon.domain.batch import BatchRecord, BatchState, ReceiptApplied
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
    RequestId,
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
    "sqlite": lambda tmp: SqliteCorpusStore.open(tmp / "state" / "corpus.sqlite3"),
}
REAL_IO = {"sqlite"}


@pytest.fixture(
    params=[
        pytest.param(name, marks=[pytest.mark.integration] if name in REAL_IO else [])
        for name in sorted(STORES)
    ]
)
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

    assert [stored.entry for stored in store.list_entries(limit=10)] == [newer]


def test_list_entries_pages_by_position_keyset(store: CorpusStorePort) -> None:
    """Given entries put in some order, When listed in pages of two after the
    last position seen, Then every entry comes once, in first-put order, with
    increasing positions."""
    urls = ["https://c.example/", "https://a.example/", "https://b.example/"]
    for url in urls:
        store.put_entry(make_entry(url))

    first = store.list_entries(limit=2)
    rest = store.list_entries(after=first[-1].position, limit=2)

    listed = first + rest
    assert [s.entry.identity.value for s in listed] == urls
    positions = [s.position for s in listed]
    assert positions == sorted(set(positions))


def test_list_entries_keeps_a_replaced_entry_at_its_position(
    store: CorpusStorePort,
) -> None:
    """Given a page read, When an entry already listed is replaced and a new one
    is put, Then the next page holds only the new entry (a cursor stays valid
    across data changes: nothing listed moves behind or ahead of it)."""
    store.put_entry(make_entry("https://b.example/"))
    store.put_entry(make_entry("https://c.example/"))
    first = store.list_entries(limit=2)

    store.put_entry(make_entry("https://b.example/", summary="re-enriched"))
    store.put_entry(make_entry("https://a.example/"))
    rest = store.list_entries(after=first[-1].position, limit=2)

    assert [s.entry.identity.value for s in rest] == ["https://a.example/"]
    assert store.list_entries(limit=1)[0].entry.summary == "re-enriched"


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


def _nearest(store: CorpusStorePort, *, placed_only: bool = False) -> list[str]:
    found = store.knn_candidates((1.0, 0.0), limit=5, placed_only=placed_only)
    return [c.identity.value for c in found]


def test_knn_candidates_follow_every_write_immediately(
    store: CorpusStorePort,
) -> None:
    """Given KNN already asked once, When an entry is added, a vector replaced
    and an entry placed, Then each next KNN reflects that write at once."""
    a, b, c = "https://a.example/", "https://b.example/", "https://c.example/"
    store.put_entry(make_entry(a, vector=(1.0, 0.0)))
    store.put_entry(make_entry(b, vector=(0.6, 0.8)))
    assert _nearest(store) == [a, b]

    store.put_entry(make_entry(a, vector=(0.0, 1.0)))
    assert _nearest(store) == [b, a]

    store.put_entry(make_entry(c, vector=(1.0, 0.0)))
    assert _nearest(store) == [c, b, a]
    assert _nearest(store, placed_only=True) == []

    store.put_placement(make_placement(a))
    assert _nearest(store, placed_only=True) == [a]


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


def test_list_jobs_in_states_keeps_first_insertion_order_across_states(
    store: CorpusStorePort,
) -> None:
    """Given jobs in several states, one moved state after insertion, When the
    jobs in a set of states are listed, Then they are exactly those, in
    first-insertion order across the states (the job loop's schedule reads
    only the unfinished jobs, not every job ever ingested)."""
    store.put_job(make_job("job-1", node_id="1", state=JobState.ENRICHED))
    store.put_job(make_job("job-2", node_id="2", state=JobState.FILED))
    store.put_job(make_job("job-3", node_id="3"))
    store.put_job(make_job("job-4", node_id="4", state=JobState.CAPTURING))
    store.put_job(make_job("job-1", node_id="1", state=JobState.CAPTURING))

    listed = store.list_jobs_in((JobState.QUEUED, JobState.CAPTURING))

    assert [j.job_id for j in listed] == ["job-1", "job-3", "job-4"]
    assert store.list_jobs_in(()) == []


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


def _receipted(
    batch_id: str, *, created_at: int, profile_id: str = "profile-a"
) -> BatchRecord:
    record = make_batch(batch_id, created_at=created_at, profile_id=profile_id)
    receipt = ReceiptApplied(
        batch_id=BatchId(batch_id),
        applied=(),
        skipped=(),
        pre_batch=True,
        snapshot=make_snapshot(),
    )
    return record.with_receipt(receipt, None)


def test_batches_awaiting_tree_are_the_receipted_ones_not_yet_resnapshotted(
    store: CorpusStorePort,
) -> None:
    """Given receipted batches, one already re-snapshotted, and a PROPOSED one,
    When the batches awaiting a tree are read, Then they are exactly the
    receipted, unmarked ones, oldest first; marking one takes it out (the
    undo guard's readiness, read by key rather than by listing every
    batch)."""
    store.put_batch(_receipted("late", created_at=3))
    store.put_batch(_receipted("early", created_at=1))
    store.put_batch(replace(_receipted("done", created_at=2), tree_since_receipt=True))
    store.put_batch(make_batch("pending", created_at=4))

    awaiting = store.batches_awaiting_tree()

    assert [r.batch.batch_id for r in awaiting] == ["early", "late"]
    store.put_batch(replace(awaiting[0], tree_since_receipt=True))
    assert [r.batch.batch_id for r in store.batches_awaiting_tree()] == ["late"]


def test_batches_in_state_are_one_profiles_batches_in_that_state(
    store: CorpusStorePort,
) -> None:
    """Given PROPOSED batches in two profiles and an APPLIED one, When one
    profile's PROPOSED batches are read, Then they are exactly its PROPOSED
    ones, oldest first, and a batch stored again APPLIED leaves the list."""
    store.put_batch(make_batch("a-2", created_at=2))
    store.put_batch(make_batch("a-1", created_at=1))
    store.put_batch(make_batch("b-1", created_at=1, profile_id="profile-b"))
    store.put_batch(make_batch("a-applied", state=BatchState.APPLIED))

    proposed = store.batches_in_state(PROFILE_A, BatchState.PROPOSED)

    assert [r.batch.batch_id for r in proposed] == ["a-1", "a-2"]
    store.put_batch(replace(proposed[0], state=BatchState.APPLIED))
    assert [
        r.batch.batch_id for r in store.batches_in_state(PROFILE_A, BatchState.PROPOSED)
    ] == ["a-2"]
    applied = store.batches_in_state(PROFILE_A, BatchState.APPLIED)
    assert [r.batch.batch_id for r in applied] == ["a-1", "a-applied"]


def test_a_released_snapshot_is_deleted_only_once_no_batch_names_it(
    store: CorpusStorePort,
) -> None:
    """Given an archived snapshot named by two batches, When it is released
    while one still names it, Then it is kept; once no batch names it, a
    release deletes it (a superseded offer-time tree is not left behind)."""
    shared = SnapshotId("tree-1")
    store.put_snapshot(shared, tree := make_snapshot())
    store.put_batch(replace(make_batch("one"), snapshot_id=shared))
    store.put_batch(replace(make_batch("two"), snapshot_id=shared))

    store.put_batch(replace(make_batch("one"), snapshot_id=SnapshotId("receipt-1")))
    store.release_snapshot(shared)
    assert store.get_snapshot(shared) == tree

    store.put_batch(replace(make_batch("two"), snapshot_id=SnapshotId("receipt-2")))
    store.release_snapshot(shared)
    assert store.get_snapshot(shared) is None


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


# --- Profiles (contract v1, Connection lifecycle: the writer's profile) ---


def test_the_writer_profile_is_bound_once(store: CorpusStorePort) -> None:
    """Given no bound profile, When one is bound and another bind is tried,
    Then the first stays bound (rebinding is a user action outside the
    contract)."""
    assert store.writer_profile() is None

    store.bind_writer_profile(PROFILE_A)
    store.bind_writer_profile(PROFILE_B)

    assert store.writer_profile() == PROFILE_A


def test_a_profiles_follow_up_folder_is_remembered(store: CorpusStorePort) -> None:
    """Given a profile's resolved Follow Up folder, When read back, Then it is
    the latest one kept; an unknown profile has none."""
    store.put_follow_up(PROFILE_A, make_path("Follow Up"))
    store.put_follow_up(PROFILE_A, make_path("Inbox", "Follow Up"))

    assert store.follow_up_of(PROFILE_A) == make_path("Inbox", "Follow Up")
    assert store.follow_up_of(PROFILE_B) is None


# --- Request-id memory (contract v1, Envelope) ---


def test_a_request_fingerprint_is_remembered_by_id(store: CorpusStorePort) -> None:
    """Given a request id's body fingerprint put, When read back, Then it is
    the one kept; an unknown id has none."""
    store.put_request(RequestId("req-1"), "sha256:abc")

    assert store.get_request(RequestId("req-1")) == "sha256:abc"
    assert store.get_request(RequestId("req-2")) is None


# --- Units of work: a use case's writes commit together or not at all ---


class _Killed(Exception):
    """The process died inside a unit of work, before it completed."""


def _state(store: CorpusStorePort) -> object:
    """Everything the tests below write, as the store reads it back."""
    return (
        [s.entry for s in store.list_entries(limit=10)],
        [c.identity for c in store.text_candidates(Query("tokio"), limit=10)],
        [c.identity for c in store.knn_candidates((1.0, 0.0), limit=10)],
        [
            c.identity
            for c in store.knn_candidates((1.0, 0.0), limit=10, placed_only=True)
        ],
        store.get_placement(Identity("https://tokio.rs/tokio/tutorial")),
        store.list_jobs(),
        store.list_batches(),
        store.unacked_events(PROFILE_A),
        store.list_diffs(),
        store.latest_tree_snapshot(),
        store.get_snapshot(SnapshotId("snap-1")),
        store.folder_flags(),
        store.writer_profile(),
        store.get_request(RequestId("req-1")),
    )


def _write_everything(store: CorpusStorePort) -> None:
    store.put_entry(make_entry(text="tokio"))
    store.put_placement(make_placement())
    store.put_job(make_job("job-2"))
    store.put_batch(make_batch("batch-1", state=BatchState.APPLIED))
    store.put_batch(make_batch("batch-2"))
    store.ack_events(PROFILE_A, [EventId("evt-1")])
    store.put_event(PROFILE_A, _job_event("evt-2"))
    store.put_diff(make_diff("diff-2"))
    store.put_tree_snapshot(make_snapshot(taken_at=2_000_000_000_000))
    store.put_snapshot(SnapshotId("snap-1"), make_snapshot())
    store.put_folder_flags(NodeId("14"), FolderFlags(pinned=True, locked=True))
    store.bind_writer_profile(PROFILE_A)
    store.put_request(RequestId("req-1"), "sha256:abc")


def _seed(store: CorpusStorePort) -> None:
    store.put_job(make_job("job-1"))
    store.put_batch(make_batch("batch-1"))
    store.put_event(PROFILE_A, _job_event("evt-1"))
    store.put_diff(make_diff("diff-1"))
    store.put_tree_snapshot(make_snapshot())


def test_writes_in_a_unit_of_work_that_completes_are_all_kept(
    store: CorpusStorePort,
) -> None:
    """Given a seeded store, When a unit of work writes to every kind of record
    and completes, Then every write reads back as if it had been made alone."""
    alone = InMemoryCorpusStore()
    _seed(alone)
    _write_everything(alone)
    _seed(store)

    with store.atomic():
        _write_everything(store)

    assert _state(store) == _state(alone)


def test_a_unit_of_work_that_raises_keeps_none_of_its_writes(
    store: CorpusStorePort,
) -> None:
    """Given a seeded store whose KNN was already read, When a unit of work
    writes to every kind of record and then raises (a crash before it
    completes), Then the store reads exactly as before, KNN and full-text
    included, and it keeps taking writes afterwards."""
    _seed(store)
    before = _state(store)

    with pytest.raises(_Killed), store.atomic():
        _write_everything(store)
        raise _Killed

    assert _state(store) == before
    store.put_job(make_job("job-3"))
    assert [j.job_id for j in store.list_jobs()] == ["job-1", "job-3"]


def test_a_unit_inside_a_unit_commits_only_with_the_outer_one(
    store: CorpusStorePort,
) -> None:
    """Given a unit of work that completes inside another, When the outer one
    raises, Then the inner one's writes are gone too."""
    with pytest.raises(_Killed), store.atomic():
        with store.atomic():
            store.put_job(make_job("job-1"))
        store.put_batch(make_batch("batch-1"))
        raise _Killed

    assert (store.list_jobs(), store.list_batches()) == ([], [])


def test_a_unit_inside_a_unit_that_raises_undoes_only_its_own_writes(
    store: CorpusStorePort,
) -> None:
    """Given an inner unit of work that raises and is caught by the outer one,
    When the outer one completes, Then its own writes are kept and the inner
    one's are not."""
    with store.atomic():
        store.put_job(make_job("job-1"))
        with pytest.raises(_Killed), store.atomic():
            store.put_batch(make_batch("batch-1"))
            store.put_entry(make_entry())
            raise _Killed
        store.put_event(PROFILE_A, _job_event("evt-1"))

    assert [j.job_id for j in store.list_jobs()] == ["job-1"]
    assert store.list_batches() == []
    assert store.list_entries(limit=10) == []
    assert store.knn_candidates((1.0, 0.0), limit=10) == []
    assert [p.event.event_id for p in store.unacked_events(PROFILE_A)] == ["evt-1"]


def test_a_failed_write_inside_a_unit_leaves_the_unit_usable(
    store: CorpusStorePort,
) -> None:
    """Given a unit of work in which one write is refused (NotFound) and the
    refusal is handled, When the unit completes, Then its other writes are
    kept."""
    with store.atomic():
        with pytest.raises(NotFound):
            store.put_diff_item(make_diff_item("item-9", diff_id="diff-9"))
        store.put_job(make_job("job-1"))

    assert [j.job_id for j in store.list_jobs()] == ["job-1"]
