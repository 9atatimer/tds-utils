"""``CorpusStorePort`` on SQLite: FTS5 for full-text candidates, float32 vectors.

Every durable thing the daemon keeps lives in one file (default
``$XDG_STATE_HOME/dynomark/corpus.sqlite3``), owner-only: its directory is
created 0700 and the file forced to 0600 (Security Considerations). Rows
hold domain values as JSON documents (``records.py``) beside the columns
that queries key on.

Search: ``text_candidates`` is an FTS5 ``MATCH`` of every query word,
ranked by ``bm25``; ``knn_candidates`` is brute-force cosine similarity in
SQL over the float32 blobs, by ``sqlite-vec``'s ``vec_distance_cosine``,
top-k by ``ORDER BY ... LIMIT``. Every store connection loads the extension;
a Python whose ``sqlite3`` cannot load extensions is refused by name. KNN
reads the table itself, so it sees exactly what this connection's
transaction sees: its own writes at once, a rollback never, and another
connection's commits from the next query.

Thread-safe: one connection, every method under one lock, each write one
transaction. ``atomic`` holds the lock and one transaction for a whole unit
of work; a write or unit inside it is a savepoint. Schema migrations are
versioned in code (``MIGRATIONS``, recorded in ``PRAGMA user_version``); a
file from a newer schema is refused.
"""

import array
import math
import os
import re
import sqlite3
import threading
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final, Self

import sqlite_vec

from dynomark_daemon.adapters.records import dump_record, load_record
from dynomark_daemon.domain.batch import BatchRecord, BatchState
from dynomark_daemon.domain.bookmark import CorpusEntry, Embedding, Identity, Save
from dynomark_daemon.domain.diff import DiffItem, TreeDiff
from dynomark_daemon.domain.events import (
    BatchOffered,
    DiffProposed,
    Event,
    JobUpdated,
    PendingEvent,
)
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
from dynomark_daemon.ports.errors import NotFound
from dynomark_daemon.ports.store import StoredEntry

# --- Constants ---

WORD: Final = re.compile(r"\w+")
DIR_MODE: Final = 0o700
FILE_MODE: Final = 0o600
BUSY_TIMEOUT_MS: Final = 5_000
EVENT_TYPES: Final[tuple[type[Event], ...]] = (JobUpdated, BatchOffered, DiffProposed)

MIGRATIONS: Final = (
    # 1: the PoC schema.
    """
    CREATE TABLE entries (
        position INTEGER PRIMARY KEY AUTOINCREMENT,
        identity TEXT NOT NULL UNIQUE,
        doc TEXT NOT NULL,
        vector BLOB NOT NULL,
        norm REAL NOT NULL,
        model_id TEXT NOT NULL
    );
    CREATE VIRTUAL TABLE entries_fts USING fts5(
        title, summary, tags, text,
        tokenize = "unicode61 remove_diacritics 0 tokenchars '_'"
    );
    CREATE TABLE placements (identity TEXT PRIMARY KEY, doc TEXT NOT NULL);
    CREATE TABLE jobs (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id TEXT NOT NULL UNIQUE,
        profile_id TEXT NOT NULL,
        node_id TEXT NOT NULL,
        identity TEXT NOT NULL,
        state TEXT NOT NULL,
        doc TEXT NOT NULL
    );
    CREATE INDEX jobs_by_save ON jobs (profile_id, node_id, identity);
    CREATE INDEX jobs_by_state ON jobs (state);
    CREATE TABLE saves (job_id TEXT PRIMARY KEY, doc TEXT NOT NULL);
    CREATE TABLE batches (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_id TEXT NOT NULL UNIQUE,
        created_at INTEGER NOT NULL,
        doc TEXT NOT NULL
    );
    CREATE TABLE tree_snapshot (
        slot INTEGER PRIMARY KEY CHECK (slot = 1),
        taken_at INTEGER NOT NULL,
        doc TEXT NOT NULL
    );
    CREATE TABLE snapshots (snapshot_id TEXT PRIMARY KEY, doc TEXT NOT NULL);
    CREATE TABLE feedback (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        feedback_id TEXT NOT NULL UNIQUE,
        observed_at INTEGER NOT NULL,
        doc TEXT NOT NULL
    );
    CREATE TABLE diffs (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        diff_id TEXT NOT NULL UNIQUE,
        proposed_at INTEGER NOT NULL,
        doc TEXT NOT NULL
    );
    CREATE TABLE diff_items (item_id TEXT PRIMARY KEY, diff_id TEXT NOT NULL);
    CREATE TABLE events (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        profile_id TEXT NOT NULL,
        event_id TEXT NOT NULL,
        pushed INTEGER NOT NULL DEFAULT 0,
        doc TEXT NOT NULL,
        UNIQUE (profile_id, event_id)
    );
    CREATE TABLE folder_flags (
        node_id TEXT PRIMARY KEY,
        pinned INTEGER NOT NULL,
        locked INTEGER NOT NULL
    );
    CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE follow_ups (profile_id TEXT PRIMARY KEY, doc TEXT NOT NULL);
    CREATE TABLE requests (request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL);
    """,
    # 2: a receipt's tree lives only in its archive, never in the batch row;
    # the batches a tree.snapshot acts on are read by index, not by decoding
    # every row; an archive no batch names is dropped.
    """
    ALTER TABLE batches ADD COLUMN profile_id TEXT NOT NULL DEFAULT '';
    ALTER TABLE batches ADD COLUMN state TEXT NOT NULL DEFAULT '';
    ALTER TABLE batches ADD COLUMN awaiting_tree INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE batches ADD COLUMN snapshot_id TEXT;
    UPDATE batches SET
        profile_id = json_extract(doc, '$.profile_id'),
        state = json_extract(doc, '$.state'),
        awaiting_tree = (
            json_type(doc, '$.receipt') = 'object'
            AND json_extract(doc, '$.tree_since_receipt') = 0
        ),
        snapshot_id = json_extract(doc, '$.snapshot_id'),
        doc = CASE json_type(doc, '$.receipt')
            WHEN 'object' THEN json_set(doc, '$.receipt.snapshot', NULL)
            ELSE doc
        END;
    CREATE INDEX batches_by_state ON batches (profile_id, state, created_at);
    CREATE INDEX batches_awaiting_tree ON batches (awaiting_tree, created_at);
    CREATE INDEX batches_by_snapshot ON batches (snapshot_id);
    DELETE FROM snapshots WHERE snapshot_id NOT IN (
        SELECT snapshot_id FROM batches WHERE snapshot_id IS NOT NULL
    );
    """,
)
SCHEMA_VERSION: Final = len(MIGRATIONS)


class StoreError(RuntimeError):
    """The store file cannot be opened or written as asked."""


@dataclass(frozen=True, slots=True)
class StoreHealth:
    """What ``dynomark-daemon check`` reports about the store."""

    path: Path
    schema_version: int
    entries: int
    jobs: int
    integrity: str
    vector_extension: str
    """The ``sqlite-vec`` version KNN runs in, as ``vec_version()`` names it."""


# --- Helpers ---


def _words(text: str) -> list[str]:
    return WORD.findall(text.lower())


def _match_expression(query: Query) -> str | None:
    """Every query word, each quoted (FTS5 implicit AND); ``None`` if none."""
    words = _words(query.text)
    return " ".join(f'"{word}"' for word in words) if words else None


def _bm25_score(rank: float) -> float:
    """``bm25`` is negative, lower is better: map it into [0, 1), higher better."""
    gain = max(0.0, -rank)
    return gain / (1.0 + gain)


def _pack(vector: Sequence[float]) -> tuple[bytes, float]:
    packed = array.array("f", vector)
    return packed.tobytes(), math.sqrt(sum(x * x for x in packed))


def _unpack(blob: bytes) -> "array.array[float]":
    vector = array.array("f")
    vector.frombytes(blob)
    return vector


def _knn_sql(*, placed_only: bool) -> str:
    """Cosine similarity of every (placed) entry to ``:query``, best first,
    ties by identity, cut to ``:limit``.

    A row scores 0.0, and stays a candidate, where there is no finite answer:
    a vector that is not a blob of exactly ``:size`` bytes (another
    dimension, empty, or a hand edit), or one with no direction or a
    component past float32 (``vec_distance_cosine`` answers NULL; SQLite
    stores a NaN as NULL too). The ``CASE`` is evaluated lazily, so a row of
    the wrong size never reaches ``vec_distance_cosine``, which raises on a
    dimension mismatch. sqlite-vec sums in float32, so a vector whose squared
    components overflow it (about 1.8e19) has no finite norm and scores 0.0.
    """
    placed = " JOIN placements p ON p.identity = e.identity" if placed_only else ""
    return (
        "SELECT e.identity, CASE WHEN :size > 0 AND typeof(e.vector) = 'blob'"
        " AND length(e.vector) = :size"
        " THEN coalesce(1.0 - vec_distance_cosine(e.vector, :query), 0.0)"
        " ELSE 0.0 END AS score"
        f" FROM entries e{placed}"
        " ORDER BY score DESC, e.identity LIMIT :limit"
    )


def _load_vector_extension(connection: sqlite3.Connection) -> str:
    """Load ``sqlite-vec`` into ``connection``; its ``vec_version()``.

    Raises:
        StoreError: this Python's ``sqlite3`` cannot load extensions (the
            macOS system Python), or the extension would not load.
    """
    try:
        connection.enable_load_extension(True)
        try:
            sqlite_vec.load(connection)
        finally:
            connection.enable_load_extension(False)
        (version,) = connection.execute("SELECT vec_version()").fetchone()
    except (AttributeError, sqlite3.Error) as error:
        raise StoreError(
            f"this Python's sqlite3 cannot load the sqlite-vec extension, which "
            f"KNN runs in ({error}); use a Python built with loadable sqlite3 "
            f"extensions (python.org, Homebrew or uv's)"
        ) from error
    return str(version)


def vector_extension_version() -> str:
    """The ``sqlite-vec`` version this Python loads, on a throwaway in-memory
    database (what ``dynomark-daemon check`` reports).

    Raises:
        StoreError: as ``_load_vector_extension``.
    """
    connection = sqlite3.connect(":memory:")
    try:
        return _load_vector_extension(connection)
    finally:
        connection.close()


def _best_first(scored: Iterable[tuple[str, float]], limit: int) -> list[Candidate]:
    ranked = sorted(scored, key=lambda row: (-row[1], row[0]))
    return [Candidate(Identity(identity), score) for identity, score in ranked[:limit]]


def _entry_doc(entry: CorpusEntry) -> str:
    """The entry without its vector, which is kept as a float32 blob."""
    bare = replace(
        entry, embedding=Embedding(vector=(), model_id=entry.embedding.model_id)
    )
    return dump_record(bare)


def _prepare_file(path: Path) -> None:
    """Create the parent directory 0700 (when missing) and the file 0600."""
    if not path.parent.exists():
        path.parent.mkdir(mode=DIR_MODE, parents=True)
        path.parent.chmod(DIR_MODE)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, FILE_MODE)
    os.close(fd)
    path.chmod(FILE_MODE)


def _migrate(connection: sqlite3.Connection, path: Path) -> None:
    (current,) = connection.execute("PRAGMA user_version").fetchone()
    if current > SCHEMA_VERSION:
        raise StoreError(
            f"{path} has schema {current}, newer than this daemon's {SCHEMA_VERSION}"
        )
    for version in range(current + 1, SCHEMA_VERSION + 1):
        script = MIGRATIONS[version - 1]
        connection.executescript(
            f"BEGIN IMMEDIATE;\n{script}\nPRAGMA user_version = {version};\nCOMMIT;"
        )


def _connect(path: Path, *, read_only: bool) -> sqlite3.Connection:
    if read_only:
        if not path.exists():
            raise StoreError(f"no store at {path}")
        target, uri = f"file:{path}?mode=ro", True
    else:
        _prepare_file(path)
        target, uri = str(path), False
    connection = sqlite3.connect(
        target, uri=uri, isolation_level=None, check_same_thread=False
    )
    connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    if not read_only:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
    return connection


# --- The adapter ---


class SqliteCorpusStore:
    def __init__(
        self, connection: sqlite3.Connection, path: Path, *, read_only: bool
    ) -> None:
        self._db = connection
        self._path = path
        self._read_only = read_only
        self._lock = threading.RLock()
        self._vector_extension = _load_vector_extension(connection)
        self._depth = 0
        """Open writes and units of work, nested; only read under the lock."""

    @classmethod
    def open(cls, path: Path, *, read_only: bool = False) -> Self:
        """Open (creating and migrating unless ``read_only``) the store at ``path``.

        Raises:
            StoreError: no file to read, a schema newer than the code, or a
                Python that cannot load ``sqlite-vec``.
        """
        connection = _connect(path, read_only=read_only)
        try:
            if read_only:
                (version,) = connection.execute("PRAGMA user_version").fetchone()
                if version > SCHEMA_VERSION:
                    raise StoreError(f"{path} has schema {version}, newer than ours")
            else:
                _migrate(connection, path)
            return cls(connection, path, read_only=read_only)
        except BaseException:
            connection.close()
            raise

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def health(self) -> StoreHealth:
        with self._lock:
            (version,) = self._db.execute("PRAGMA user_version").fetchone()
            (entries,) = self._db.execute("SELECT count(*) FROM entries").fetchone()
            (jobs,) = self._db.execute("SELECT count(*) FROM jobs").fetchone()
            (integrity,) = self._db.execute("PRAGMA quick_check").fetchone()
        return StoreHealth(
            path=self._path,
            schema_version=int(version),
            entries=int(entries),
            jobs=int(jobs),
            integrity=str(integrity),
            vector_extension=self._vector_extension,
        )

    # --- Plumbing ---

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        """One transaction, committed on success, rolled back on error; inside
        another, a savepoint, released on success and rolled back to on
        error, so only the outermost commits."""
        if self._read_only:
            raise StoreError(f"{self._path} is open read-only")
        with self._lock:
            outermost = self._depth == 0
            self._db.execute("BEGIN IMMEDIATE" if outermost else "SAVEPOINT unit")
            self._depth += 1
            try:
                yield self._db
            except BaseException:
                if outermost:
                    self._db.execute("ROLLBACK")
                else:
                    self._db.execute("ROLLBACK TO unit")
                    self._db.execute("RELEASE unit")
                raise
            finally:
                self._depth -= 1
            try:
                self._db.execute("COMMIT" if outermost else "RELEASE unit")
            except BaseException:
                # A failed COMMIT (a full or failing disk) is rolled back by
                # SQLite, or left open. An open one is rolled back here, or
                # every later BEGIN IMMEDIATE fails. A failed RELEASE is left
                # to the enclosing unit, which rolls back on this error.
                if outermost and self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise

    # --- Units of work ---

    @contextmanager
    def atomic(self) -> Iterator[None]:
        with self._write():
            yield

    def _one(
        self, sql: str, params: Sequence[object] = ()
    ) -> tuple[object, ...] | None:
        with self._lock:
            row: tuple[object, ...] | None = self._db.execute(sql, params).fetchone()
        return row

    def _all(
        self, sql: str, params: Sequence[object] | Mapping[str, object] = ()
    ) -> list[tuple[object, ...]]:
        with self._lock:
            rows: list[tuple[object, ...]] = self._db.execute(sql, params).fetchall()
        return rows

    def _doc(self, sql: str, params: Sequence[object] = ()) -> str | None:
        row = self._one(sql, params)
        return None if row is None else str(row[0])

    def _docs(self, sql: str, params: Sequence[object] = ()) -> list[str]:
        return [str(row[0]) for row in self._all(sql, params)]

    def _entry(self, doc: object, vector: object) -> CorpusEntry:
        bare = load_record(str(doc), CorpusEntry)
        values = tuple(_unpack(bytes(vector))) if isinstance(vector, bytes) else ()
        embedding = Embedding(vector=values, model_id=bare.embedding.model_id)
        return replace(bare, embedding=embedding)

    # --- Entries ---

    def put_entry(self, entry: CorpusEntry) -> None:
        blob, norm = _pack(entry.embedding.vector)
        with self._write() as db:
            db.execute(
                "INSERT INTO entries (identity, doc, vector, norm, model_id)"
                " VALUES (?, ?, ?, ?, ?) ON CONFLICT (identity) DO UPDATE SET"
                " doc = excluded.doc, vector = excluded.vector,"
                " norm = excluded.norm, model_id = excluded.model_id",
                (
                    entry.identity.value,
                    _entry_doc(entry),
                    blob,
                    norm,
                    entry.embedding.model_id,
                ),
            )
            (position,) = db.execute(
                "SELECT position FROM entries WHERE identity = ?",
                (entry.identity.value,),
            ).fetchone()
            db.execute("DELETE FROM entries_fts WHERE rowid = ?", (position,))
            db.execute(
                "INSERT INTO entries_fts (rowid, title, summary, tags, text)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    position,
                    entry.bookmark.title,
                    entry.summary,
                    " ".join(entry.tags),
                    entry.capture.text,
                ),
            )

    def get_entry(self, identity: Identity) -> CorpusEntry | None:
        row = self._one(
            "SELECT doc, vector FROM entries WHERE identity = ?", (identity.value,)
        )
        return None if row is None else self._entry(row[0], row[1])

    def list_entries(
        self, *, after: int | None = None, limit: int
    ) -> list[StoredEntry]:
        rows = self._all(
            "SELECT position, doc, vector FROM entries WHERE position > ?"
            " ORDER BY position LIMIT ?",
            (after or 0, limit),
        )
        return [
            StoredEntry(position=int(str(position)), entry=self._entry(doc, vector))
            for position, doc, vector in rows
        ]

    # --- Candidates ---

    def text_candidates(self, query: Query, *, limit: int) -> list[Candidate]:
        expression = _match_expression(query)
        if expression is None:
            return []
        rows = self._all(
            "SELECT e.identity, bm25(entries_fts) FROM entries_fts"
            " JOIN entries e ON e.position = entries_fts.rowid"
            " WHERE entries_fts MATCH ?",
            (expression,),
        )
        return _best_first(
            ((str(identity), _bm25_score(float(str(rank)))) for identity, rank in rows),
            limit,
        )

    def knn_candidates(
        self, vector: Sequence[float], *, limit: int, placed_only: bool = False
    ) -> list[Candidate]:
        query = _pack(vector)[0]
        rows = self._all(
            _knn_sql(placed_only=placed_only),
            {"query": query, "size": len(query), "limit": limit},
        )
        return [
            Candidate(Identity(str(identity)), float(str(score)))
            for identity, score in rows
        ]

    # --- Placements ---

    def put_placement(self, placement: Placement) -> None:
        with self._write() as db:
            db.execute(
                "INSERT OR REPLACE INTO placements (identity, doc) VALUES (?, ?)",
                (placement.identity.value, dump_record(placement)),
            )

    def get_placement(self, identity: Identity) -> Placement | None:
        doc = self._doc(
            "SELECT doc FROM placements WHERE identity = ?", (identity.value,)
        )
        return None if doc is None else load_record(doc, Placement)

    # --- Jobs ---

    def put_job(self, job: Job) -> None:
        with self._write() as db:
            db.execute(
                "INSERT INTO jobs (job_id, profile_id, node_id, identity, state, doc)"
                " VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (job_id) DO UPDATE SET"
                " profile_id = excluded.profile_id, node_id = excluded.node_id,"
                " identity = excluded.identity, state = excluded.state,"
                " doc = excluded.doc",
                (
                    job.job_id,
                    job.profile_id,
                    job.node_id,
                    job.identity.value,
                    job.state.value,
                    dump_record(job),
                ),
            )

    def get_job(self, job_id: JobId) -> Job | None:
        doc = self._doc("SELECT doc FROM jobs WHERE job_id = ?", (job_id,))
        return None if doc is None else load_record(doc, Job)

    def find_job(
        self, profile_id: ProfileId, node_id: NodeId, identity: Identity
    ) -> Job | None:
        doc = self._doc(
            "SELECT doc FROM jobs WHERE profile_id = ? AND node_id = ?"
            " AND identity = ? ORDER BY seq LIMIT 1",
            (profile_id, node_id, identity.value),
        )
        return None if doc is None else load_record(doc, Job)

    def list_jobs(self, *, state: JobState | None = None) -> list[Job]:
        if state is None:
            docs = self._docs("SELECT doc FROM jobs ORDER BY seq")
        else:
            docs = self._docs(
                "SELECT doc FROM jobs WHERE state = ? ORDER BY seq", (state.value,)
            )
        return [load_record(doc, Job) for doc in docs]

    def list_jobs_in(self, states: Collection[JobState]) -> list[Job]:
        values = sorted({state.value for state in states})
        if not values:
            return []
        marks = ", ".join("?" * len(values))
        docs = self._docs(
            f"SELECT doc FROM jobs WHERE state IN ({marks}) ORDER BY seq", values
        )
        return [load_record(doc, Job) for doc in docs]

    def put_save(self, job_id: JobId, save: Save) -> None:
        with self._write() as db:
            db.execute(
                "INSERT OR REPLACE INTO saves (job_id, doc) VALUES (?, ?)",
                (job_id, dump_record(save)),
            )

    def get_save(self, job_id: JobId) -> Save | None:
        doc = self._doc("SELECT doc FROM saves WHERE job_id = ?", (job_id,))
        return None if doc is None else load_record(doc, Save)

    # --- Batches ---

    def put_batch(self, record: BatchRecord) -> None:
        awaiting = record.receipt is not None and not record.tree_since_receipt
        with self._write() as db:
            db.execute(
                "INSERT INTO batches (batch_id, created_at, profile_id, state,"
                " awaiting_tree, snapshot_id, doc) VALUES (?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (batch_id) DO UPDATE SET"
                " created_at = excluded.created_at, profile_id = excluded.profile_id,"
                " state = excluded.state, awaiting_tree = excluded.awaiting_tree,"
                " snapshot_id = excluded.snapshot_id, doc = excluded.doc",
                (
                    record.batch.batch_id,
                    record.created_at,
                    record.profile_id,
                    record.state.value,
                    int(awaiting),
                    record.snapshot_id,
                    dump_record(record),
                ),
            )

    def get_batch(self, batch_id: BatchId) -> BatchRecord | None:
        doc = self._doc("SELECT doc FROM batches WHERE batch_id = ?", (batch_id,))
        return None if doc is None else load_record(doc, BatchRecord)

    def list_batches(self) -> list[BatchRecord]:
        docs = self._docs("SELECT doc FROM batches ORDER BY created_at DESC, seq DESC")
        return [load_record(doc, BatchRecord) for doc in docs]

    def batches_awaiting_tree(self) -> list[BatchRecord]:
        docs = self._docs(
            "SELECT doc FROM batches WHERE awaiting_tree = 1 ORDER BY created_at, seq"
        )
        return [load_record(doc, BatchRecord) for doc in docs]

    def batches_in_state(
        self, profile_id: ProfileId, state: BatchState
    ) -> list[BatchRecord]:
        docs = self._docs(
            "SELECT doc FROM batches WHERE profile_id = ? AND state = ?"
            " ORDER BY created_at, seq",
            (profile_id, state.value),
        )
        return [load_record(doc, BatchRecord) for doc in docs]

    # --- Snapshots ---

    def put_tree_snapshot(self, snapshot: Snapshot) -> None:
        with self._write() as db:
            db.execute(
                "INSERT INTO tree_snapshot (slot, taken_at, doc) VALUES (1, ?, ?)"
                " ON CONFLICT (slot) DO UPDATE SET taken_at = excluded.taken_at,"
                " doc = excluded.doc WHERE excluded.taken_at >= tree_snapshot.taken_at",
                (snapshot.taken_at, dump_record(snapshot)),
            )

    def latest_tree_snapshot(self) -> Snapshot | None:
        doc = self._doc("SELECT doc FROM tree_snapshot WHERE slot = 1")
        return None if doc is None else load_record(doc, Snapshot)

    def put_snapshot(self, snapshot_id: SnapshotId, snapshot: Snapshot) -> None:
        with self._write() as db:
            db.execute(
                "INSERT OR REPLACE INTO snapshots (snapshot_id, doc) VALUES (?, ?)",
                (snapshot_id, dump_record(snapshot)),
            )

    def get_snapshot(self, snapshot_id: SnapshotId) -> Snapshot | None:
        doc = self._doc(
            "SELECT doc FROM snapshots WHERE snapshot_id = ?", (snapshot_id,)
        )
        return None if doc is None else load_record(doc, Snapshot)

    def release_snapshot(self, snapshot_id: SnapshotId) -> None:
        with self._write() as db:
            db.execute(
                "DELETE FROM snapshots WHERE snapshot_id = ? AND NOT EXISTS"
                " (SELECT 1 FROM batches WHERE snapshot_id = ?)",
                (snapshot_id, snapshot_id),
            )

    # --- Feedback ---

    def put_feedback(self, feedback: MoveFeedback) -> None:
        with self._write() as db:
            db.execute(
                "INSERT OR IGNORE INTO feedback (feedback_id, observed_at, doc)"
                " VALUES (?, ?, ?)",
                (feedback.feedback_id, feedback.observed_at, dump_record(feedback)),
            )

    def recent_feedback(self, *, limit: int) -> list[MoveFeedback]:
        docs = self._docs(
            "SELECT doc FROM feedback ORDER BY observed_at DESC, seq DESC LIMIT ?",
            (limit,),
        )
        return [load_record(doc, MoveFeedback) for doc in docs]

    # --- Diffs ---

    def put_diff(self, diff: TreeDiff) -> None:
        with self._write() as db:
            self._write_diff(db, diff)

    def _write_diff(self, db: sqlite3.Connection, diff: TreeDiff) -> None:
        db.execute(
            "INSERT INTO diffs (diff_id, proposed_at, doc) VALUES (?, ?, ?)"
            " ON CONFLICT (diff_id) DO UPDATE SET"
            " proposed_at = excluded.proposed_at, doc = excluded.doc",
            (diff.diff_id, diff.proposed_at, dump_record(diff)),
        )
        db.execute("DELETE FROM diff_items WHERE diff_id = ?", (diff.diff_id,))
        db.executemany(
            "INSERT OR REPLACE INTO diff_items (item_id, diff_id) VALUES (?, ?)",
            [(item.item_id, diff.diff_id) for item in diff.items],
        )

    def get_diff(self, diff_id: DiffId) -> TreeDiff | None:
        doc = self._doc("SELECT doc FROM diffs WHERE diff_id = ?", (diff_id,))
        return None if doc is None else load_record(doc, TreeDiff)

    def list_diffs(self) -> list[TreeDiff]:
        docs = self._docs("SELECT doc FROM diffs ORDER BY proposed_at DESC, seq DESC")
        return [load_record(doc, TreeDiff) for doc in docs]

    def put_diff_item(self, item: DiffItem) -> None:
        with self._write() as db:
            row = db.execute(
                "SELECT doc FROM diffs WHERE diff_id = ?", (item.diff_id,)
            ).fetchone()
            diff = None if row is None else load_record(str(row[0]), TreeDiff)
            if diff is None or item.item_id not in {i.item_id for i in diff.items}:
                raise NotFound(f"no diff {item.diff_id} holds item {item.item_id}")
            items = tuple(item if i.item_id == item.item_id else i for i in diff.items)
            self._write_diff(db, replace(diff, items=items))

    def get_diff_item(self, item_id: ItemId) -> DiffItem | None:
        row = self._one("SELECT diff_id FROM diff_items WHERE item_id = ?", (item_id,))
        diff = None if row is None else self.get_diff(DiffId(str(row[0])))
        items = () if diff is None else diff.items
        return next((i for i in items if i.item_id == item_id), None)

    # --- Events ---

    def put_event(self, profile_id: ProfileId, event: Event) -> None:
        with self._write() as db:
            db.execute(
                "INSERT OR IGNORE INTO events (profile_id, event_id, doc)"
                " VALUES (?, ?, ?)",
                (profile_id, event.event_id, dump_record(event)),
            )

    def unacked_events(self, profile_id: ProfileId) -> list[PendingEvent]:
        rows = self._all(
            "SELECT doc, pushed FROM events WHERE profile_id = ? ORDER BY seq",
            (profile_id,),
        )
        return [
            PendingEvent(
                event=load_record(str(doc), Event, EVENT_TYPES), pushed=bool(pushed)
            )
            for doc, pushed in rows
        ]

    def mark_pushed(self, profile_id: ProfileId, event_ids: Iterable[EventId]) -> None:
        with self._write() as db:
            db.executemany(
                "UPDATE events SET pushed = 1 WHERE profile_id = ? AND event_id = ?",
                [(profile_id, event_id) for event_id in event_ids],
            )

    def ack_events(self, profile_id: ProfileId, event_ids: Iterable[EventId]) -> None:
        with self._write() as db:
            db.executemany(
                "DELETE FROM events WHERE profile_id = ? AND event_id = ?",
                [(profile_id, event_id) for event_id in event_ids],
            )

    # --- Owned-folder flags ---

    def put_folder_flags(self, node_id: NodeId, flags: FolderFlags) -> None:
        with self._write() as db:
            db.execute(
                "INSERT OR REPLACE INTO folder_flags (node_id, pinned, locked)"
                " VALUES (?, ?, ?)",
                (node_id, int(flags.pinned), int(flags.locked)),
            )

    def folder_flags(self) -> dict[NodeId, FolderFlags]:
        rows = self._all("SELECT node_id, pinned, locked FROM folder_flags")
        return {
            NodeId(str(node_id)): FolderFlags(pinned=bool(pinned), locked=bool(locked))
            for node_id, pinned, locked in rows
        }

    # --- Profiles ---

    def writer_profile(self) -> ProfileId | None:
        doc = self._doc("SELECT value FROM meta WHERE key = 'writer_profile'")
        return None if doc is None else ProfileId(doc)

    def bind_writer_profile(self, profile_id: ProfileId) -> None:
        with self._write() as db:
            db.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES ('writer_profile', ?)",
                (profile_id,),
            )

    def put_follow_up(self, profile_id: ProfileId, path: FolderPath) -> None:
        with self._write() as db:
            db.execute(
                "INSERT OR REPLACE INTO follow_ups (profile_id, doc) VALUES (?, ?)",
                (profile_id, dump_record(path)),
            )

    def follow_up_of(self, profile_id: ProfileId) -> FolderPath | None:
        doc = self._doc(
            "SELECT doc FROM follow_ups WHERE profile_id = ?", (profile_id,)
        )
        return None if doc is None else load_record(doc, FolderPath)

    # --- Request-id memory ---

    def put_request(self, request_id: RequestId, fingerprint: str) -> None:
        with self._write() as db:
            db.execute(
                "INSERT OR REPLACE INTO requests (request_id, fingerprint)"
                " VALUES (?, ?)",
                (request_id, fingerprint),
            )

    def get_request(self, request_id: RequestId) -> str | None:
        return self._doc(
            "SELECT fingerprint FROM requests WHERE request_id = ?", (request_id,)
        )
