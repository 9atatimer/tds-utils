"""Retention (DYNOMARK.DESIGN.md, Key Decisions: Retention 2026-10-16; issue
#421): a corpus entry, its saves and placement go 30 days after its bookmark
leaves the tree; archived snapshots go after 30 days unless an undo needs
them; batch rows stay; answered requests go.

``enforce_retention(*, store, clock, keep_ms) -> Retained`` is clock-driven:
the job loop runs it. An entry's bookmark is in the tree when the writer's
latest tree snapshot holds a bookmark of its identity; the first sweep that
finds it gone records when, and a sweep that finds it back clears that.
"""

from dataclasses import replace

import pytest

from dynomark_daemon.app.diffs import request_diff
from dynomark_daemon.app.errors import InvalidRequest
from dynomark_daemon.app.jobs import retry_job
from dynomark_daemon.app.retention import enforce_retention
from dynomark_daemon.app.tree import record_tree_snapshot
from dynomark_daemon.domain.bookmark import Identity, Save
from dynomark_daemon.domain.diff import DiffKind
from dynomark_daemon.domain.ids import BatchId, JobId, ProfileId, RequestId, SnapshotId
from dynomark_daemon.domain.job import JobState
from dynomark_daemon.domain.retention import RETENTION_MS
from dynomark_daemon.domain.roles import HostRole
from dynomark_daemon.domain.tree import Snapshot
from dynomark_daemon.testing.clock import FakeClock, SequentialIds
from dynomark_daemon.testing.completion import ScriptedCompletion
from dynomark_daemon.testing.store import InMemoryCorpusStore
from tests._factories import (
    make_batch,
    make_bookmark,
    make_capture,
    make_entry,
    make_job,
    make_node,
    make_placement,
    make_roots,
    make_snapshot,
    make_tree,
)

A, B = ProfileId("profile-a"), ProfileId("profile-b")
URL = "https://tokio.rs/tokio/tutorial"
TOKIO = Identity(URL)
DAY = 86_400_000
FOLLOW_UP = make_node("10", "1", "Follow Up")
WITH_BOOKMARK = make_tree(FOLLOW_UP, make_node("42", "10", "Tokio", url=URL))
WITHOUT_BOOKMARK = make_tree(FOLLOW_UP)


class Daemon:
    """A writer's store holding one filed entry of profile A, and a clock."""

    def __init__(self, *, state: JobState = JobState.FILED, profile: str = "profile-a"):
        self.store = InMemoryCorpusStore()
        self.clock = FakeClock(start_ms=1_000)
        self.store.bind_writer_profile(A)
        self.store.put_entry(make_entry(URL, text="tokio"))
        self.store.put_placement(make_placement(URL))
        self.store.put_job(make_job("job-1", state=state, profile_id=profile))
        self.store.put_save(
            JobId("job-1"),
            Save(bookmark=make_bookmark(URL), capture=make_capture("tokio")),
        )
        self.store.put_batch(
            replace(make_batch("batch-1"), job_id=JobId("job-1"), identity=TOKIO)
        )

    def tree(self, tree: Snapshot) -> None:
        self.store.put_tree_snapshot(replace(tree, taken_at=self.clock.now_ms()))

    def sweep(self) -> None:
        enforce_retention(store=self.store, clock=self.clock, keep_ms=RETENTION_MS)

    def kept(self) -> bool:
        return self.store.get_entry(TOKIO) is not None


def test_an_entry_gone_from_the_tree_for_30_days_is_dropped_with_its_records() -> None:
    """Given a filed entry whose bookmark left the tree, When sweeps run as 30
    days pass, Then it is kept until 30 days after the first sweep that found
    it gone, and then its entry, save and placement go; its batch row and job
    stay."""
    daemon = Daemon()
    daemon.tree(WITHOUT_BOOKMARK)

    daemon.sweep()
    daemon.clock.advance(RETENTION_MS - 1)
    daemon.sweep()
    kept_until_due = daemon.kept()
    daemon.clock.advance(1)
    daemon.sweep()

    assert kept_until_due
    assert not daemon.kept()
    assert daemon.store.get_save(JobId("job-1")) is None
    assert daemon.store.get_placement(TOKIO) is None
    assert daemon.store.get_batch(BatchId("batch-1")) is not None
    assert daemon.store.get_job(JobId("job-1")) is not None


def test_a_bookmark_back_in_the_tree_restarts_its_30_days() -> None:
    """Given an entry found gone, When its bookmark is back at a later sweep,
    Then the absence is cleared: gone again later, it is kept for a full 30
    days from then."""
    daemon = Daemon()
    daemon.tree(WITHOUT_BOOKMARK)
    daemon.sweep()
    daemon.clock.advance(20 * DAY)
    daemon.tree(WITH_BOOKMARK)
    daemon.sweep()
    daemon.clock.advance(20 * DAY)
    daemon.tree(WITHOUT_BOOKMARK)
    daemon.sweep()

    daemon.clock.advance(RETENTION_MS - 1)
    daemon.sweep()

    assert daemon.kept()
    assert daemon.store.absences() == {TOKIO: 1_000 + 40 * DAY}


def test_an_entry_still_in_the_tree_is_never_dropped() -> None:
    """Given an entry whose bookmark stays in the tree, When 60 days of sweeps
    run, Then it is kept and never tracked absent."""
    daemon = Daemon()
    daemon.tree(WITH_BOOKMARK)

    for _ in range(3):
        daemon.sweep()
        daemon.clock.advance(RETENTION_MS)

    assert daemon.kept() and daemon.store.absences() == {}


def test_an_entry_with_a_job_still_running_is_kept() -> None:
    """Given an entry whose job is still running (PLACED), When sweeps run past
    30 days with its bookmark absent from the writer's tree, Then it is kept:
    a running job needs its records."""
    daemon = Daemon(state=JobState.PLACED)
    daemon.tree(WITHOUT_BOOKMARK)

    daemon.sweep()
    daemon.clock.advance(RETENTION_MS)
    daemon.sweep()

    assert daemon.kept()


def test_an_entry_saved_only_by_a_profile_with_no_tree_is_judged_by_known_trees() -> (
    None
):
    """Given an entry saved (INDEXED) only from profile B, whose tree this
    daemon has never been sent, When its bookmark is absent from every known
    tree for 30 days, Then it is dropped: a profile that is not known vouches
    for nothing, so it cannot keep captured text forever (issue #534 T4)."""
    daemon = Daemon(state=JobState.INDEXED, profile="profile-b")
    daemon.tree(WITHOUT_BOOKMARK)

    daemon.sweep()
    daemon.clock.advance(RETENTION_MS)
    daemon.sweep()

    assert not daemon.kept()


def test_after_reinstall_and_rebind_the_old_profiles_entry_still_leaves() -> None:
    """Given profile A's filed entry, When the extension is reinstalled (new
    profile C), the owner runs rebind, C binds and C's tree lacks the
    bookmark for 30 days, Then the entry is dropped: A's settled job no
    longer keeps it once A is not a known profile (issue #534 T4)."""
    daemon = Daemon()
    daemon.store.release_writer_profile()
    daemon.store.bind_writer_profile(ProfileId("profile-c"))
    daemon.tree(WITHOUT_BOOKMARK)

    daemon.sweep()
    daemon.clock.advance(RETENTION_MS)
    daemon.sweep()

    assert not daemon.kept()


def _reader_tree(daemon: Daemon, profile: ProfileId, tree: Snapshot) -> None:
    """``profile``'s connection, served reader, sends its tree."""
    stamped = replace(tree, taken_at=daemon.clock.now_ms())
    record_tree_snapshot(stamped, HostRole.READER, profile, store=daemon.store)


def test_a_reader_profiles_entry_gone_from_its_tree_for_30_days_is_dropped() -> None:
    """Given a writer serving profile B as a reader, and B's save (INDEXED),
    When B's own tree no longer holds the bookmark for 30 days, Then the entry
    is dropped: Retention keeps B's latest tree though B never files (issue
    #421)."""
    daemon = Daemon(state=JobState.INDEXED, profile="profile-b")
    daemon.tree(WITHOUT_BOOKMARK)
    _reader_tree(daemon, B, WITHOUT_BOOKMARK)

    daemon.sweep()
    daemon.clock.advance(RETENTION_MS)
    daemon.sweep()

    assert not daemon.kept()


def test_a_reader_daemon_drops_an_entry_gone_30_days_from_its_profiles_tree() -> None:
    """Given a daemon configured reader (no writer binding, no latest tree), and
    profile A's save, When A's tree no longer holds the bookmark for 30 days,
    Then the entry is dropped (a reader host saw nothing disappear before)."""
    daemon = Daemon(state=JobState.INDEXED)
    daemon.store.release_writer_profile()
    _reader_tree(daemon, A, WITHOUT_BOOKMARK)

    daemon.sweep()
    daemon.clock.advance(RETENTION_MS)
    daemon.sweep()

    assert not daemon.kept()


def test_an_entry_another_known_profiles_tree_still_holds_is_kept() -> None:
    """Given an entry the writer's profile A filed and profile B saved too, When
    A's tree loses the bookmark but B's latest tree still holds it, Then sweeps
    past 30 days keep it: an entry is absent only when no known profile's
    latest tree holds its URL."""
    daemon = Daemon()
    daemon.store.put_job(
        make_job("job-b", node_id="77", state=JobState.INDEXED, profile_id="profile-b")
    )
    daemon.tree(WITHOUT_BOOKMARK)
    _reader_tree(daemon, B, WITH_BOOKMARK)

    daemon.sweep()
    daemon.clock.advance(RETENTION_MS)
    daemon.sweep()

    assert daemon.kept() and daemon.store.absences() == {}


def test_an_abandoned_reader_profiles_tree_stops_keeping_an_entry() -> None:
    """Given profile B, served reader, whose last tree held the bookmark and
    which never connects again, When sweeps run as the writer's tree lacks
    it, Then B's tree is forgotten once over 30 days old (as an archived
    snapshot is; B is no longer known), and the entry goes 30 days after
    that (issue #534 T4)."""
    daemon = Daemon()
    daemon.tree(WITHOUT_BOOKMARK)
    _reader_tree(daemon, B, WITH_BOOKMARK)

    daemon.sweep()
    daemon.clock.advance(RETENTION_MS)
    daemon.sweep()
    known_until_due = B in daemon.store.profile_trees()
    daemon.clock.advance(1)
    daemon.sweep()
    forgotten = B not in daemon.store.profile_trees()
    kept_after_forgotten = daemon.kept()
    daemon.clock.advance(RETENTION_MS)
    daemon.sweep()

    assert known_until_due and forgotten and kept_after_forgotten
    assert not daemon.kept()


def test_no_tree_snapshot_tracks_and_drops_no_entry() -> None:
    """Given no tree snapshot at all (a reader host keeps none), When sweeps
    run past 30 days, Then no entry is tracked absent or dropped."""
    daemon = Daemon()

    daemon.sweep()
    daemon.clock.advance(RETENTION_MS)
    daemon.sweep()

    assert daemon.kept() and daemon.store.absences() == {}


def test_archived_snapshots_go_after_30_days_and_batch_rows_stay() -> None:
    """Given an archive taken over 30 days ago and one taken since, When swept,
    Then only the old archive goes and the batch that named it stays, naming
    none: no undo reads an archive (it runs on the latest tree snapshot and
    the batch's receipt)."""
    daemon = Daemon()
    daemon.clock.advance(RETENTION_MS + DAY)
    now = daemon.clock.now_ms()
    old, new = SnapshotId("tree-old"), SnapshotId("tree-new")
    daemon.store.put_snapshot(old, make_snapshot(taken_at=now - RETENTION_MS - 1))
    daemon.store.put_snapshot(new, make_snapshot(taken_at=now - DAY))
    daemon.store.put_batch(
        replace(make_batch("batch-old"), snapshot_id=old, created_at=1_000)
    )

    daemon.sweep()

    assert daemon.store.get_snapshot(old) is None
    assert daemon.store.get_snapshot(new) is not None
    batch = daemon.store.get_batch(BatchId("batch-old"))
    assert batch is not None and batch.snapshot_id is None


def _propose(daemon: Daemon, request_id: str, kind: DiffKind) -> str:
    diff = request_diff(
        RequestId(request_id),
        kind,
        HostRole.WRITER,
        make_roots(),
        store=daemon.store,
        completion=ScriptedCompletion(propose_diff=[()]),
        clock=daemon.clock,
        ids=SequentialIds(),
    )
    return diff.diff_id


def test_an_answered_request_is_forgotten_and_its_retry_still_answers_once() -> None:
    """Given a diff.propose answered and another remembered but unanswered,
    When swept, Then only the answered one is forgotten; When the answered
    id is sent again, Then the same diff is returned, and with another body
    it is still invalid."""
    daemon = Daemon()
    daemon.tree(WITH_BOOKMARK)
    first = _propose(daemon, "req-1", DiffKind.REBUILD)
    daemon.store.put_request(RequestId("req-2"), "sha256:unanswered")

    daemon.sweep()

    assert daemon.store.list_requests() == [RequestId("req-2")]
    assert _propose(daemon, "req-1", DiffKind.REBUILD) == first
    with pytest.raises(InvalidRequest):
        _propose(daemon, "req-1", DiffKind.AUDIT)


def test_retrying_a_failed_job_whose_save_was_dropped_is_invalid() -> None:
    """Given a FAILED job whose entry and save were dropped by retention, When
    the user retries it, Then it is refused as invalid -- the job is known,
    nothing is left to process (contract v2) -- and the job stays FAILED."""
    daemon = Daemon(state=JobState.FAILED)
    daemon.tree(WITHOUT_BOOKMARK)
    daemon.sweep()
    daemon.clock.advance(RETENTION_MS)
    daemon.sweep()

    with pytest.raises(InvalidRequest):
        retry_job(
            JobId("job-1"),
            A,
            store=daemon.store,
            clock=daemon.clock,
            ids=SequentialIds(),
        )

    job = daemon.store.get_job(JobId("job-1"))
    assert job is not None and job.state is JobState.FAILED
