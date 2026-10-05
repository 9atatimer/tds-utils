"""SqliteCorpusStore beyond the shared port contract: the file on disk.

Design: Security Considerations ("Page content of logged-in sessions on
disk ... owner-only permissions in the user's state directory"); task-025
("schema migrations versioned in code"; "vectors as float32 blobs").
"""

import array
import sqlite3
import stat
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from dynomark_daemon.adapters.records import dump_record
from dynomark_daemon.adapters.sqlite_store import (
    MIGRATIONS,
    SCHEMA_VERSION,
    SqliteCorpusStore,
    StoreError,
)
from dynomark_daemon.domain.batch import BatchRecord, BatchState, ReceiptApplied
from dynomark_daemon.domain.bookmark import Save
from dynomark_daemon.domain.events import JobUpdated
from dynomark_daemon.domain.ids import (
    BatchId,
    EventId,
    JobId,
    NodeId,
    ProfileId,
    RequestId,
    SnapshotId,
)
from dynomark_daemon.domain.tree import FolderFlags, Snapshot
from tests._factories import (
    make_batch,
    make_bookmark,
    make_capture,
    make_entry,
    make_feedback,
    make_job,
    make_placement,
    make_snapshot,
)

pytestmark = pytest.mark.integration

A = ProfileId("profile-a")


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_open_creates_an_owner_only_directory_and_database(tmp_path: Path) -> None:
    """Given no state directory, When the store is opened, Then the directory is
    0700 and the database file 0600."""
    db = tmp_path / "state" / "dynomark" / "corpus.sqlite3"

    SqliteCorpusStore.open(db).close()

    assert _mode(db.parent) == 0o700
    assert _mode(db) == 0o600


def test_open_tightens_an_existing_database_file_to_owner_only(
    tmp_path: Path,
) -> None:
    """Given a database file readable by others, When opened, Then it is 0600."""
    db = tmp_path / "corpus.sqlite3"
    SqliteCorpusStore.open(db).close()
    db.chmod(0o644)

    SqliteCorpusStore.open(db).close()

    assert _mode(db) == 0o600


def test_everything_put_survives_a_reopen(tmp_path: Path) -> None:
    """Given every kind of record put, When the store is closed and reopened,
    Then each reads back the same (durable before acknowledgement)."""
    db = tmp_path / "corpus.sqlite3"
    entry = make_entry(summary="a runtime", tags=("rust",), text="Tokio text")
    job = make_job()
    save = Save(bookmark=make_bookmark(), capture=make_capture("Tokio text"))
    batch = make_batch()
    event = JobUpdated(event_id=EventId("evt-1"), job=job)
    store = SqliteCorpusStore.open(db)
    store.put_entry(entry)
    store.put_placement(placement := make_placement())
    store.put_job(job)
    store.put_save(job.job_id, save)
    store.put_batch(batch)
    store.put_tree_snapshot(tree := make_snapshot())
    store.put_feedback(feedback := make_feedback("fb-1"))
    store.put_event(A, event)
    store.put_folder_flags(NodeId("14"), FolderFlags(pinned=True, locked=False))
    store.bind_writer_profile(A)
    store.put_request(RequestId("req-1"), "sha256:abc")
    store.close()

    reopened = SqliteCorpusStore.open(db)

    assert reopened.get_entry(entry.identity) == entry
    assert reopened.get_placement(entry.identity) == placement
    assert reopened.get_job(job.job_id) == job
    assert reopened.get_save(JobId(job.job_id)) == save
    assert reopened.get_batch(batch.batch.batch_id) == batch
    assert reopened.latest_tree_snapshot() == tree
    assert reopened.recent_feedback(limit=5) == [feedback]
    assert [p.event for p in reopened.unacked_events(A)] == [event]
    assert reopened.folder_flags() == {
        NodeId("14"): FolderFlags(pinned=True, locked=False)
    }
    assert reopened.writer_profile() == A
    assert reopened.get_request(RequestId("req-1")) == "sha256:abc"


def test_a_new_database_is_migrated_to_the_schema_version_in_code(
    tmp_path: Path,
) -> None:
    """Given a new file, When opened twice, Then its schema is the version the
    code carries and the second open migrates nothing (data kept)."""
    db = tmp_path / "corpus.sqlite3"
    first = SqliteCorpusStore.open(db)
    first.put_entry(entry := make_entry())
    first.close()

    second = SqliteCorpusStore.open(db)

    assert second.health().schema_version == SCHEMA_VERSION >= 1
    assert second.get_entry(entry.identity) == entry


def test_a_database_from_a_newer_schema_is_refused(tmp_path: Path) -> None:
    """Given a database whose schema is newer than the code, When opened, Then
    StoreError says so instead of running against an unknown schema."""
    db = tmp_path / "corpus.sqlite3"
    SqliteCorpusStore.open(db).close()
    with sqlite3.connect(db) as raw:
        raw.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")

    with pytest.raises(StoreError, match="newer"):
        SqliteCorpusStore.open(db)


def test_vectors_are_kept_at_float32_precision(tmp_path: Path) -> None:
    """Given an entry whose vector is not exact in float32, When read back, Then
    the vector is its float32 rounding and still finds itself nearest."""
    vector = (0.1, 0.2, 0.3)
    store = SqliteCorpusStore.open(tmp_path / "corpus.sqlite3")
    store.put_entry(make_entry(vector=vector))

    entry = store.get_entry(make_entry().identity)

    assert entry is not None
    assert entry.embedding.vector == tuple(array.array("f", vector))
    (nearest,) = store.knn_candidates(vector, limit=1)
    assert nearest.identity == entry.identity and round(nearest.score, 6) == 1.0


def _traced_store(db: Path, statements: list[str]) -> SqliteCorpusStore:
    """A store over a connection whose every statement lands in ``statements``."""
    SqliteCorpusStore.open(db).close()
    connection = sqlite3.connect(db, isolation_level=None, check_same_thread=False)
    connection.set_trace_callback(statements.append)
    return SqliteCorpusStore(connection, db, read_only=False)


def _nearest(store: SqliteCorpusStore, *, placed_only: bool = False) -> list[str]:
    found = store.knn_candidates((1.0, 0.0), limit=5, placed_only=placed_only)
    return [c.identity.value for c in found]


def test_knn_reads_the_vectors_from_the_file_only_once(tmp_path: Path) -> None:
    """Given KNN asked once, When it is asked again (placed or not) and after a
    write, Then no statement reads a vector blob back from the file (Goal 4
    tier 2: the fetch and unpack of every vector is not paid per query)."""
    statements: list[str] = []
    store = _traced_store(tmp_path / "corpus.sqlite3", statements)
    store.put_entry(make_entry("https://a.example/", vector=(1.0, 0.0)))
    store.put_placement(make_placement("https://a.example/"))
    _nearest(store)
    statements.clear()

    store.put_entry(make_entry("https://b.example/", vector=(0.6, 0.8)))
    statements.clear()
    unplaced, placed = _nearest(store), _nearest(store, placed_only=True)

    assert (unplaced, placed) == (
        ["https://a.example/", "https://b.example/"],
        ["https://a.example/"],
    )
    assert not [s for s in statements if "vector" in s.lower()]


def test_knn_follows_writes_made_through_another_connection(tmp_path: Path) -> None:
    """Given a read-only store that has answered KNN, When another connection
    replaces a vector, deletes an entry and places one, Then the reader's next
    KNN reflects each change (the check command beside a running daemon)."""
    db = tmp_path / "corpus.sqlite3"
    writer = SqliteCorpusStore.open(db)
    writer.put_entry(make_entry("https://a.example/", vector=(1.0, 0.0)))
    writer.put_entry(make_entry("https://b.example/", vector=(0.6, 0.8)))
    reader = SqliteCorpusStore.open(db, read_only=True)
    assert _nearest(reader) == ["https://a.example/", "https://b.example/"]

    writer.put_entry(make_entry("https://a.example/", vector=(0.0, 1.0)))
    assert _nearest(reader) == ["https://b.example/", "https://a.example/"]

    with sqlite3.connect(db) as raw:
        raw.execute("DELETE FROM entries WHERE identity = 'https://b.example/'")
    assert _nearest(reader) == ["https://a.example/"]
    assert _nearest(reader, placed_only=True) == []

    writer.put_placement(make_placement("https://a.example/"))
    assert _nearest(reader, placed_only=True) == ["https://a.example/"]


def test_a_failed_replace_leaves_knn_on_the_committed_vector(tmp_path: Path) -> None:
    """Given KNN asked once, When replacing an entry's vector fails inside its
    transaction, Then KNN still ranks by the vector that was committed.

    The trigger is created before the first KNN: a commit through another
    connection after it would move ``data_version`` and reload the cache from
    the table, hiding whatever ``put_entry`` did to the cache."""
    db = tmp_path / "corpus.sqlite3"
    store = SqliteCorpusStore.open(db)
    store.put_entry(make_entry("https://a.example/", vector=(1.0, 0.0)))
    store.put_entry(make_entry("https://b.example/", vector=(0.6, 0.8)))
    with sqlite3.connect(db) as raw:
        raw.execute(
            "CREATE TRIGGER refuse AFTER UPDATE ON entries"
            " BEGIN SELECT RAISE(ABORT, 'refused'); END"
        )
    assert _nearest(store) == ["https://a.example/", "https://b.example/"]

    with pytest.raises(sqlite3.IntegrityError, match="refused"):
        store.put_entry(make_entry("https://a.example/", vector=(0.0, 1.0)))

    assert _nearest(store) == ["https://a.example/", "https://b.example/"]


class _CommitFails:
    """A connection whose next ``COMMIT``, once armed, fails as a full or
    failing disk fails it: rolled back by SQLite (``rolls_back``), or left
    open (a failure SQLite does not roll back for you). Everything else goes
    to the real connection."""

    def __init__(self, db: Path, *, rolls_back: bool) -> None:
        self._db = sqlite3.connect(db, isolation_level=None, check_same_thread=False)
        self._rolls_back = rolls_back
        self.armed = False

    def execute(self, sql: str, parameters: Sequence[object] = ()) -> sqlite3.Cursor:
        if sql == "COMMIT" and self.armed:
            self.armed = False
            if self._rolls_back:
                self._db.execute("ROLLBACK")
            raise sqlite3.OperationalError("disk I/O error")
        return self._db.execute(sql, parameters)

    def __getattr__(self, name: str) -> object:
        return getattr(self._db, name)


@pytest.mark.parametrize("rolls_back", [True, False])
def test_a_unit_whose_commit_fails_leaves_knn_and_later_writes_on_what_was_committed(
    tmp_path: Path, rolls_back: bool
) -> None:
    """Given KNN asked once, When a unit of work writes vectors and its COMMIT
    fails (rolled back by SQLite, or left open), Then the error reaches the
    caller, KNN ranks only what was committed, and the next write commits."""
    db = tmp_path / "corpus.sqlite3"
    SqliteCorpusStore.open(db).close()
    connection = _CommitFails(db, rolls_back=rolls_back)
    store = SqliteCorpusStore(cast(sqlite3.Connection, connection), db, read_only=False)
    store.put_entry(make_entry("https://a.example/", vector=(1.0, 0.0)))
    assert _nearest(store) == ["https://a.example/"]

    connection.armed = True
    with pytest.raises(sqlite3.OperationalError, match="disk I/O"), store.atomic():
        store.put_entry(make_entry("https://ghost.example/", vector=(1.0, 0.0)))

    assert _nearest(store) == ["https://a.example/"]
    store.put_entry(make_entry("https://b.example/", vector=(0.6, 0.8)))
    store.close()
    reopened = SqliteCorpusStore.open(db)
    try:
        assert _nearest(reopened) == ["https://a.example/", "https://b.example/"]
    finally:
        reopened.close()


@pytest.mark.parametrize("placed_only", [False, True])
def test_a_vector_beyond_float32_ranks_as_unrelated_not_unordered(
    tmp_path: Path, placed_only: bool
) -> None:
    """Given a placed entry whose vector overflows float32 (stored as inf, so
    its cosine is inf/inf), When KNN ranks every placed entry, Then it scores
    0.0 and the rest keep their order (a NaN score breaks ``sorted``, and the
    placed rows come out of a set, so the top-k varied with the hash seed)."""
    store = SqliteCorpusStore.open(tmp_path / "corpus.sqlite3")
    for url, vector in (
        ("https://a.example/", (1.0, 0.0)),
        ("https://b.example/", (1e39, 1.0)),
        ("https://c.example/", (1.0, 1.0)),
    ):
        store.put_entry(make_entry(url, vector=vector))
        store.put_placement(make_placement(url))

    found = store.knn_candidates((1.0, 0.0), limit=5, placed_only=placed_only)

    assert [(c.identity.value, round(c.score, 3)) for c in found] == [
        ("https://a.example/", 1.0),
        ("https://c.example/", 0.707),
        ("https://b.example/", 0.0),
    ]


@pytest.mark.parametrize("placed_only", [False, True])
def test_a_vector_that_is_not_float32_ranks_as_unrelated_not_an_error(
    tmp_path: Path, placed_only: bool
) -> None:
    """Given placed entries whose vector a hand edit left as a blob of no whole
    float32 count, or as text, When KNN ranks them, Then each scores 0.0 and
    is still a candidate, and the matching entry still comes first."""
    db = tmp_path / "corpus.sqlite3"
    store = SqliteCorpusStore.open(db)
    for url in ("https://a.example/", "https://odd.example/", "https://text.example/"):
        store.put_entry(make_entry(url, vector=(1.0, 0.0)))
        store.put_placement(make_placement(url))
    with sqlite3.connect(db) as raw:
        raw.execute(
            "UPDATE entries SET vector = CASE identity"
            " WHEN 'https://odd.example/' THEN x'00000000000080'"
            " ELSE 'eight ch' END WHERE identity != 'https://a.example/'"
        )

    found = store.knn_candidates((1.0, 0.0), limit=5, placed_only=placed_only)

    assert [(c.identity.value, round(c.score, 3)) for c in found] == [
        ("https://a.example/", 1.0),
        ("https://odd.example/", 0.0),
        ("https://text.example/", 0.0),
    ]


@pytest.mark.parametrize("read_only", [False, True])
def test_health_names_the_sqlite_vec_version_the_store_searches_with(
    tmp_path: Path, read_only: bool
) -> None:
    """Given a store opened for writing or read-only, When its health is read,
    Then it names the sqlite-vec version loaded on its connection (KNN runs
    in that extension)."""
    db = tmp_path / "corpus.sqlite3"
    SqliteCorpusStore.open(db).close()
    store = SqliteCorpusStore.open(db, read_only=read_only)

    try:
        version = store.health().vector_extension
    finally:
        store.close()

    assert version.startswith("v0.")


class _NoExtensions:
    """A connection from a Python whose sqlite3 was built without loadable
    extensions (the macOS system Python): ``enable_load_extension`` is absent."""

    def __init__(self, db: Path) -> None:
        self._db = sqlite3.connect(db, isolation_level=None, check_same_thread=False)

    def __getattr__(self, name: str) -> object:
        if name in ("enable_load_extension", "load_extension"):
            raise AttributeError(name)
        return getattr(self._db, name)

    def close(self) -> None:
        self._db.close()


def test_a_python_that_cannot_load_sqlite_vec_is_refused_by_name(
    tmp_path: Path,
) -> None:
    """Given a connection that cannot load extensions, When a store is built on
    it, Then StoreError names sqlite-vec instead of KNN failing on the first
    search."""
    db = tmp_path / "corpus.sqlite3"
    SqliteCorpusStore.open(db).close()
    connection = _NoExtensions(db)

    try:
        with pytest.raises(StoreError, match="sqlite-vec"):
            SqliteCorpusStore(cast(sqlite3.Connection, connection), db, read_only=False)
    finally:
        connection.close()


def test_health_counts_entries_and_jobs_and_checks_integrity(tmp_path: Path) -> None:
    """Given a store with one entry and two jobs, When its health is read, Then
    it reports the schema version, the counts and an ok integrity check."""
    store = SqliteCorpusStore.open(tmp_path / "corpus.sqlite3")
    store.put_entry(make_entry())
    store.put_job(make_job("job-1", node_id="1"))
    store.put_job(make_job("job-2", node_id="2"))

    health = store.health()

    assert (health.schema_version, health.entries, health.jobs) == (
        SCHEMA_VERSION,
        1,
        2,
    )
    assert health.integrity == "ok"


def test_a_read_only_open_never_creates_a_missing_database(tmp_path: Path) -> None:
    """Given no database file, When opened read-only (the check command), Then
    StoreError is raised and no file is created."""
    db = tmp_path / "state" / "corpus.sqlite3"

    with pytest.raises(StoreError, match="no store"):
        SqliteCorpusStore.open(db, read_only=True)

    assert not db.exists() and not db.parent.exists()


def test_a_read_only_open_reads_but_never_writes(tmp_path: Path) -> None:
    """Given a store with an entry, When opened read-only, Then it reads the
    entry and a write raises StoreError."""
    db = tmp_path / "corpus.sqlite3"
    writer = SqliteCorpusStore.open(db)
    writer.put_entry(entry := make_entry())
    writer.close()

    reader = SqliteCorpusStore.open(db, read_only=True)

    assert reader.get_entry(entry.identity) == entry
    with pytest.raises(StoreError):
        reader.put_job(make_job())


def test_a_unit_of_work_is_not_on_disk_until_it_completes(tmp_path: Path) -> None:
    """Given a unit of work that has written a job and its event, When another
    connection reads the file before the unit completes, Then neither is
    there (a crash now loses both); once it completes, both are."""
    db = tmp_path / "corpus.sqlite3"
    store = SqliteCorpusStore.open(db)
    try:
        with store.atomic():
            store.put_job(make_job())
            store.put_event(A, JobUpdated(event_id=EventId("evt-1"), job=make_job()))
            reader = SqliteCorpusStore.open(db, read_only=True)
            try:
                assert (reader.list_jobs(), reader.unacked_events(A)) == ([], [])
            finally:
                reader.close()
        reader = SqliteCorpusStore.open(db, read_only=True)
        try:
            assert [j.job_id for j in reader.list_jobs()] == ["job-1"]
            assert len(reader.unacked_events(A)) == 1
        finally:
            reader.close()
    finally:
        store.close()


def test_a_read_only_store_refuses_a_unit_of_work(tmp_path: Path) -> None:
    """Given a store opened read-only, When a unit of work is opened, Then it is
    refused like any write."""
    db = tmp_path / "corpus.sqlite3"
    SqliteCorpusStore.open(db).close()
    reader = SqliteCorpusStore.open(db, read_only=True)
    try:
        with pytest.raises(StoreError), reader.atomic():
            pass
    finally:
        reader.close()


# --- Batches: the tree.snapshot path reads by key ---


def _receipted(batch_id: str, tree: Snapshot) -> BatchRecord:
    receipt = ReceiptApplied(
        batch_id=BatchId(batch_id),
        applied=(),
        skipped=(),
        pre_batch=True,
        snapshot=tree,
    )
    return make_batch(batch_id).with_receipt(receipt, SnapshotId(f"receipt-{batch_id}"))


def _plans(db: Path, statements: list[str]) -> list[str]:
    """The query plan of every traced read of the batches table."""
    with sqlite3.connect(db) as raw:
        return [
            " ".join(str(row[-1]) for row in raw.execute(f"EXPLAIN QUERY PLAN {sql}"))
            for sql in statements
            if sql.lstrip().upper().startswith("SELECT") and "batches" in sql
        ]


def test_the_batches_a_tree_snapshot_needs_are_read_by_index(tmp_path: Path) -> None:
    """Given receipted and PROPOSED batches, When the batches awaiting a tree
    and one profile's PROPOSED batches are read, Then every read of the
    batches table searches an index rather than scanning it: the cost of a
    ``tree.snapshot`` follows what it acts on, not every filing on record."""
    db = tmp_path / "corpus.sqlite3"
    statements: list[str] = []
    store = _traced_store(db, statements)
    store.put_batch(_receipted("receipted", make_snapshot()))
    store.put_batch(make_batch("pending"))
    statements.clear()

    awaiting = store.batches_awaiting_tree()
    proposed = store.batches_in_state(A, BatchState.PROPOSED)

    assert [r.batch.batch_id for r in awaiting] == ["receipted"]
    assert [r.batch.batch_id for r in proposed] == ["pending"]
    plans = _plans(db, statements)
    assert len(plans) == 2
    assert all("SCAN" not in plan and "INDEX" in plan for plan in plans), plans


def test_a_batch_row_does_not_hold_its_receipts_tree(tmp_path: Path) -> None:
    """Given a receipt carrying the pre-batch tree, When its batch is stored,
    Then the row's document holds none of the tree's nodes (the tree lives
    once, in the archive the batch names)."""
    db = tmp_path / "corpus.sqlite3"
    store = SqliteCorpusStore.open(db)
    store.put_batch(_receipted("batch-1", make_snapshot(title="Unmistakable Bar")))
    store.close()

    with sqlite3.connect(db) as raw:
        (doc,) = raw.execute("SELECT doc FROM batches").fetchone()

    assert "Unmistakable Bar" not in doc
    assert "SnapshotNode" not in doc


def test_a_version_1_file_is_migrated_off_trees_in_batch_rows(tmp_path: Path) -> None:
    """Given a schema-1 file whose receipted batch row holds the receipt's
    tree, an archived receipt tree the batch names and an offer-time tree
    none names, When opened, Then the row keeps the receipt without its tree,
    the batch awaits a tree snapshot by key, the named archive is kept and
    the orphan is gone."""
    db = tmp_path / "corpus.sqlite3"
    tree = make_snapshot(title="Unmistakable Bar")
    receipt = ReceiptApplied(
        batch_id=BatchId("batch-1"),
        applied=(),
        skipped=(),
        pre_batch=True,
        snapshot=tree,
    )
    record = replace(
        make_batch("batch-1"),
        state=BatchState.APPLIED,
        receipt=receipt,
        snapshot_id=SnapshotId("receipt-batch-1"),
    )
    with sqlite3.connect(db, isolation_level=None) as raw:
        raw.executescript(MIGRATIONS[0])
        raw.execute("PRAGMA user_version = 1")
        raw.execute(
            "INSERT INTO batches (batch_id, created_at, doc) VALUES (?, ?, ?)",
            ("batch-1", record.created_at, dump_record(record)),
        )
        for snapshot_id in ("receipt-batch-1", "tree-1"):
            raw.execute(
                "INSERT INTO snapshots (snapshot_id, doc) VALUES (?, ?)",
                (snapshot_id, dump_record(tree)),
            )
    raw.close()

    store = SqliteCorpusStore.open(db)

    migrated = store.get_batch(BatchId("batch-1"))
    assert migrated == replace(record, receipt=replace(receipt, snapshot=None))
    assert [r.batch.batch_id for r in store.batches_awaiting_tree()] == ["batch-1"]
    assert store.get_snapshot(SnapshotId("receipt-batch-1")) == tree
    assert store.get_snapshot(SnapshotId("tree-1")) is None
    store.close()
    with sqlite3.connect(db) as raw:
        (doc,) = raw.execute("SELECT doc FROM batches").fetchone()
    assert "Unmistakable Bar" not in doc
