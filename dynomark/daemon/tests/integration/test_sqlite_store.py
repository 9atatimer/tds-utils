"""SqliteCorpusStore beyond the shared port contract: the file on disk.

Design: Security Considerations ("Page content of logged-in sessions on
disk ... owner-only permissions in the user's state directory"); task-025
("schema migrations versioned in code"; "vectors as float32 blobs").
"""

import array
import sqlite3
import stat
from pathlib import Path

import pytest

from dynomark_daemon.adapters.sqlite_store import (
    SCHEMA_VERSION,
    SqliteCorpusStore,
    StoreError,
)
from dynomark_daemon.domain.bookmark import Save
from dynomark_daemon.domain.events import JobUpdated
from dynomark_daemon.domain.ids import EventId, JobId, NodeId, ProfileId, RequestId
from dynomark_daemon.domain.tree import FolderFlags
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
