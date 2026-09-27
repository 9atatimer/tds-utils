"""End to end, in process (task-025 item 8): the composed daemon -- SQLite
store, unix socket, job loop -- with fakes for the models and the fetch,
driven by a client speaking contract v1 frames:

hello -> tree.snapshot -> ingest -> batch.offer -> batch.receipt APPLIED ->
job FILED -> index.pull -> search -> undo.

Design Goal 2's interval (ingest received -> APPLIED) is logged as JSON in
the state directory.
"""

import asyncio
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from dynomark_daemon.adapters.sqlite_store import SqliteCorpusStore
from dynomark_daemon.container import Daemon, Ports, RandomIds, SystemClock
from dynomark_daemon.domain.bookmark import Capture, CaptureSource, Enrichment
from dynomark_daemon.domain.placement import FolderChoice
from dynomark_daemon.logs import configure_logging
from dynomark_daemon.settings import Settings, parse_settings
from dynomark_daemon.testing.completion import ScriptedCompletion
from dynomark_daemon.testing.content import FakeFetch
from dynomark_daemon.testing.embedding import HashingEmbedding
from tests import _client as client
from tests import _wire as wire
from tests._client import EventPredicate, JsonObject
from tests._factories import make_bookmark, make_node, make_path, make_tree

pytestmark = pytest.mark.integration

TIMEOUT_S = 10.0
CAPTURED = "Tokio schedules tasks cooperatively; cancellation happens at awaits."
AFTER_FILING = make_tree(
    make_node("10", "1", "Follow Up"),
    make_node("11", "1", "Dynomark", index=1),
    make_node("12", "1", "Graveyard", index=2),
    make_node("14", "11", "Rust"),
    make_node("13", "11", "dynomark-writer:mbp", index=1),
    make_node("42", "14", "Tokio tutorial", url=wire.URL),
    taken_at=1_790_000_100_000,
)


def _settings(tmp_path: Path) -> Settings:
    return parse_settings(
        {"role": "writer", "host_id": "mbp"},
        {
            "XDG_STATE_HOME": str(tmp_path / "state"),
            "DYNOMARK_SOCKET": str(tmp_path / "d.sock"),
        },
        home=tmp_path,
        hostname="mbp",
    )


@contextmanager
def _serving(settings: Settings) -> Iterator[Daemon]:
    settings.state_dir.mkdir(parents=True, mode=0o700)
    configure_logging(settings.log_path)
    ports = Ports(
        store=SqliteCorpusStore.open(Path(settings.config.store_path)),
        embedding=HashingEmbedding(),
        completion=ScriptedCompletion(
            enrich=[Enrichment(summary="An async runtime.", tags=("rust", "async"))],
            choose_folder=[
                FolderChoice(folder=make_path("Dynomark", "Rust"), rationale="rust")
            ],
        ),
        content=FakeFetch({}),
        clock=SystemClock(),
        ids=RandomIds(),
    )
    daemon = Daemon(settings, ports)
    loop = asyncio.new_event_loop()
    stop = asyncio.Event()
    ready = threading.Event()

    async def main() -> None:
        await daemon.start()
        ready.set()
        await daemon.run_until(stop)

    thread = threading.Thread(target=loop.run_until_complete, args=(main(),))
    thread.start()
    assert ready.wait(TIMEOUT_S), "daemon did not start"
    try:
        yield daemon
    finally:
        loop.call_soon_threadsafe(stop.set)
        thread.join(TIMEOUT_S)
        loop.close()
        configure_logging(None)


def _receipt_for(offer: JsonObject) -> bytes:
    batch = offer["batch"]
    assert isinstance(batch, dict)
    operations = batch["operations"]
    assert isinstance(operations, list)
    node_ids = [str(op.get("node_id", f"new-{op['index']}")) for op in operations]
    return wire.applied_receipt("r-1", str(batch["batch_id"]), node_ids)


def test_a_save_is_filed_found_and_undone_through_the_socket(tmp_path: Path) -> None:
    """Given a writer daemon and a connected extension, When a Follow Up save is
    ingested and its offered batch applied, Then the job is FILED, the index
    and search find it by a word only in its captured text, undo offers the
    inverse, and the log holds Goal 2's interval for the job."""
    settings = _settings(tmp_path)
    with _serving(settings), client.connect(settings.socket_path) as conn:
        client.send(conn, wire.hello())
        greeting, _ = client.answer_to(conn, "h-1")
        client.send(conn, wire.tree_snapshot("t-1"))
        client.answer_to(conn, "t-1")
        client.send(conn, wire.body("events.replay", "e-1"))
        replayed, _ = client.answer_to(conn, "e-1")

        save = Capture(source=CaptureSource.TAB, text=CAPTURED, title="Tutorial")
        client.send(conn, wire.ingest("i-1", make_bookmark(wire.URL), save))
        ingested, early = client.answer_to(conn, "i-1")
        events = early + client.events_until(conn, EventPredicate("batch.offer"))
        offer = events[-1]

        client.send(conn, _receipt_for(offer))
        client.answer_to(conn, "r-1")
        filed = client.events_until(conn, EventPredicate("job.updated", "FILED"))
        client.send(conn, wire.tree_snapshot("t-2", AFTER_FILING))
        client.answer_to(conn, "t-2")

        client.send(conn, wire.body("index.pull", "p-1"))
        index, _ = client.answer_to(conn, "p-1")
        client.send(conn, wire.body("search", "q-1", query="cancellation"))
        found, _ = client.answer_to(conn, "q-1")

        batch = offer["batch"]
        assert isinstance(batch, dict)
        client.send(conn, wire.body("undo", "u-1", batch_id=batch["batch_id"]))
        undone, before_undo = client.answer_to(conn, "u-1")
        inverse = before_undo + client.events_until(conn, EventPredicate("batch.offer"))

    assert (greeting["role"], greeting["mode"], replayed["count"]) == (
        "writer",
        "full",
        0,
    )
    job = ingested["job"]
    assert isinstance(job, dict) and job["state"] == "QUEUED"
    filed_job = filed[-1]["job"]
    assert isinstance(filed_job, dict) and filed_job["job_id"] == job["job_id"]
    rows = index["rows"]
    assert isinstance(rows, list)
    (row,) = rows
    assert (row["identity"], row["path"]["names"], row["tags"]) == (
        "https://tokio.rs/tokio/tutorial",
        ["Dynomark", "Rust"],
        ["rust", "async"],
    )
    hits = found["hits"]
    assert isinstance(hits, list)
    assert [h["identity"] for h in hits] == ["https://tokio.rs/tokio/tutorial"]
    assert undone["type"] == "undo.result" and undone["batch_id"] is not None
    assert undone["dropped"] == []
    inverse_batch = inverse[-1]["batch"]
    assert isinstance(inverse_batch, dict)
    assert inverse_batch["batch_id"] == undone["batch_id"]

    lines = [json.loads(line) for line in settings.log_path.read_text().splitlines()]
    (applied,) = [e for e in lines if e["event"] == "job.applied"]
    assert applied["job_id"] == job["job_id"]
    assert applied["interval_ms"] == applied["applied_at"] - applied["received_at"] >= 0
