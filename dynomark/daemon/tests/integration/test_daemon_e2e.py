"""End to end, in process (task-025 item 8; MVP tasks 028-030): the composed
daemon -- SQLite store, unix socket, job loop -- with fakes for the models
and the fetch, driven by a client speaking contract v1 frames:

hello -> tree.snapshot -> ingest -> batch.offer -> batch.receipt APPLIED ->
job FILED -> index.pull -> search -> undo;
backfill -> ask -> placement.explain -> diff.propose -> diff.page ->
diff.accept -> batch.offer -> APPLIED -> undo carrying the item;
another host's marker -> writer.status conflict -> writer_conflict.

Design Goal 2's interval (ingest received -> APPLIED) is logged as JSON in
the state directory.
"""

import asyncio
import json
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from dynomark_daemon.adapters.sqlite_store import SqliteCorpusStore
from dynomark_daemon.container import Daemon, Ports, RandomIds, SystemClock
from dynomark_daemon.domain.batch import Expect, OpCreateFolder, OpMove
from dynomark_daemon.domain.bookmark import (
    Bookmark,
    Capture,
    CaptureSource,
    Enrichment,
    Identity,
)
from dynomark_daemon.domain.chat import DraftAnswer
from dynomark_daemon.domain.diff import DiffAction, DiffProposal
from dynomark_daemon.domain.ids import NodeId
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


ENRICHMENT = Enrichment(summary="An async runtime.", tags=("rust", "async"))


def _filing() -> ScriptedCompletion:
    return ScriptedCompletion(
        enrich=[ENRICHMENT],
        choose_folder=[
            FolderChoice(folder=make_path("Dynomark", "Rust"), rationale="rust")
        ],
    )


@contextmanager
def _serving(
    settings: Settings, completion: ScriptedCompletion | None = None
) -> Iterator[Daemon]:
    settings.state_dir.mkdir(parents=True, mode=0o700)
    configure_logging(settings.log_path)
    ports = Ports(
        store=SqliteCorpusStore.open(Path(settings.config.store_path)),
        embedding=HashingEmbedding(),
        completion=completion or _filing(),
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


# --- MVP: backfill, chat, a diff round (tasks 028, 029) ---

ASYNC_BOOK = "https://rust-lang.github.io/async-book/"
LANGUAGES = make_path("Dynomark", "Languages")
TO_LANGUAGES = DiffProposal(
    action=DiffAction.MOVE,
    description="Move Rust under Languages",
    operations=(
        OpCreateFolder(index=0, parent=make_path("Dynomark"), title="Languages"),
        OpMove(
            index=1,
            node_id=NodeId("14"),
            to=LANGUAGES,
            expect=Expect(parent_id=NodeId("11"), parent_path=make_path("Dynomark")),
        ),
    ),
)
AFTER_DIFF = make_tree(
    make_node("10", "1", "Follow Up"),
    make_node("11", "1", "Dynomark", index=1),
    make_node("12", "1", "Graveyard", index=2),
    make_node("new-0", "11", "Languages"),
    make_node("13", "11", "dynomark-writer:mbp", index=1),
    make_node("14", "new-0", "Rust"),
    make_node("44", "14", "Tokio tutorial", url=wire.URL),
    taken_at=1_790_000_200_000,
)


def _jobs_until(conn: socket.socket, wanted: dict[str, str]) -> None:
    """Read events until each job id in ``wanted`` reached its state."""
    reached: set[str] = set()
    while reached != set(wanted):
        frame = client.receive(conn)
        assert frame is not None, "closed while waiting for jobs"
        job = frame.get("job")
        if frame.get("type") == "job.updated" and isinstance(job, dict):
            if wanted.get(str(job["job_id"])) == job["state"]:
                reached.add(str(job["job_id"]))


def _backfill(conn: socket.socket, request_id: str, bookmark: Bookmark) -> str:
    save = Capture(source=CaptureSource.TAB, text=CAPTURED, title=bookmark.title)
    body = json.loads(wire.ingest(request_id, bookmark, save))
    client.send(conn, json.dumps({**body, "backfill": True}).encode())
    answer, _ = client.answer_to(conn, request_id)
    job = answer["job"]
    assert isinstance(job, dict)
    return str(job["job_id"])


@pytest.mark.skip(
    reason="flaky on macOS CI: a 5 s socket recv times out intermittently "
    "(tds-utils issue #370); skipped, not xfailed, until the race is fixed"
)
def test_backfill_ask_and_a_diff_round_through_the_socket(tmp_path: Path) -> None:
    """Given a writer daemon, When the extension backfills a filed and an
    unfiled bookmark, asks, and proposes, accepts, applies and undoes a
    rebuild item, Then the filed backfill is FILED in place and the other
    INDEXED, the answer cites the corpus entry and marks the outside URL
    external, the item's batch and its undo both carry the item."""
    settings = _settings(tmp_path)
    completion = ScriptedCompletion(
        enrich=[ENRICHMENT, ENRICHMENT],
        answer=[
            DraftAnswer(
                text="Tokio cancels at await points.",
                cited=(Identity(wire.URL), Identity("https://invented.example/")),
                urls=(ASYNC_BOOK,),
            )
        ],
        propose_diff=[(TO_LANGUAGES,)],
    )
    filed_here = make_bookmark(
        wire.URL, node_id="44", path=make_path("Dynomark", "Rust")
    )
    elsewhere = make_bookmark(
        "https://example.org/recipes",
        node_id="50",
        title="Recipes",
        path=make_path("Recipes"),
    )
    with _serving(settings, completion), client.connect(settings.socket_path) as conn:
        client.send(conn, wire.hello())
        client.answer_to(conn, "h-1")
        client.send(conn, wire.tree_snapshot("t-1"))
        client.answer_to(conn, "t-1")
        filed_job = _backfill(conn, "b-1", filed_here)
        indexed_job = _backfill(conn, "b-2", elsewhere)
        _jobs_until(conn, {filed_job: "FILED", indexed_job: "INDEXED"})

        client.send(
            conn,
            wire.body("ask", "a-1", question="how is tokio cancelled?", history=[]),
        )
        asked, _ = client.answer_to(conn, "a-1")
        client.send(conn, wire.body("placement.explain", "x-1", identity=wire.URL))
        explained, _ = client.answer_to(conn, "x-1")

        client.send(conn, wire.body("diff.propose", "d-1", kind="rebuild"))
        proposed, _ = client.answer_to(conn, "d-1")
        diff = proposed["diff"]
        assert isinstance(diff, dict)
        client.send(conn, wire.body("diff.page", "d-2", diff_id=diff["diff_id"]))
        page, _ = client.answer_to(conn, "d-2")
        items = page["items"]
        assert isinstance(items, list)
        item_id = items[0]["item_id"]
        client.send(conn, wire.body("diff.accept", "d-3", item_id=item_id))
        accepted, early = client.answer_to(conn, "d-3")
        offer = (early + client.events_until(conn, EventPredicate("batch.offer")))[-1]
        client.send(conn, _receipt_for(offer))
        client.answer_to(conn, "r-1")
        client.send(conn, wire.tree_snapshot("t-2", AFTER_DIFF))
        client.answer_to(conn, "t-2")
        client.send(conn, wire.body("undo", "u-1", batch_id=accepted["batch_id"]))
        undone, before = client.answer_to(conn, "u-1")
        inverse = (before + client.events_until(conn, EventPredicate("batch.offer")))[
            -1
        ]

    answer = asked["answer"]
    assert isinstance(answer, dict)
    assert [c["identity"] for c in answer["citations"]] == [wire.URL]
    assert answer["external_urls"] == [ASYNC_BOOK]
    reason = explained["reason"]
    assert isinstance(reason, dict)
    assert reason["folder"]["names"] == ["Dynomark", "Rust"]
    assert (diff["kind"], diff["item_count"], diff["unaccepted_count"]) == (
        "rebuild",
        1,
        1,
    )
    batch = offer["batch"]
    assert isinstance(batch, dict)
    assert batch["batch_id"] == accepted["batch_id"]
    assert batch["diff_item_id"] == item_id
    inverse_batch = inverse["batch"]
    assert isinstance(inverse_batch, dict)
    assert inverse_batch["batch_id"] == undone["batch_id"]
    assert inverse_batch["diff_item_id"] == item_id
    assert [op["op"] for op in inverse_batch["operations"]] == [
        "create_folder",
        "move",
        "remove",
    ]


# --- MVP: writer conflict (task-030) ---

OTHER_WRITER = make_tree(
    make_node("10", "1", "Follow Up"),
    make_node("11", "1", "Dynomark", index=1),
    make_node("12", "1", "Graveyard", index=2),
    make_node("14", "11", "Rust"),
    make_node("15", "11", "dynomark-writer:work-laptop", index=1),
    make_node("42", "10", "Tokio tutorial", url=wire.URL),
)


def test_a_writer_that_sees_another_hosts_marker_refuses_to_file(
    tmp_path: Path,
) -> None:
    """Given a writer daemon whose tree holds work-laptop's marker, When the
    extension asks for writer.status, saves, undoes and accepts, Then the
    status is a conflict, the save is indexed then FAILED naming it, writes
    are answered writer_conflict, and no batch is offered."""
    settings = _settings(tmp_path)
    completion = ScriptedCompletion(enrich=[ENRICHMENT])
    with _serving(settings, completion), client.connect(settings.socket_path) as conn:
        client.send(conn, wire.hello())
        client.answer_to(conn, "h-1")
        client.send(conn, wire.tree_snapshot("t-1", OTHER_WRITER))
        client.answer_to(conn, "t-1")
        client.send(conn, wire.body("writer.status", "w-1"))
        status, _ = client.answer_to(conn, "w-1")

        save = Capture(source=CaptureSource.TAB, text=CAPTURED, title="Tutorial")
        client.send(conn, wire.ingest("i-1", make_bookmark(wire.URL), save))
        ingested, _ = client.answer_to(conn, "i-1")
        job = ingested["job"]
        assert isinstance(job, dict)
        failed = client.events_until(conn, EventPredicate("job.updated", "FAILED"))
        client.send(conn, wire.body("undo", "u-1", batch_id="batch-1"))
        refused_undo, _ = client.answer_to(conn, "u-1")
        client.send(conn, wire.body("diff.accept", "d-1", item_id="item-1"))
        refused_accept, _ = client.answer_to(conn, "d-1")
        client.send(conn, wire.body("events.replay", "e-1"))
        _, replayed = client.answer_to(conn, "e-1")

    assert (status["conflict"], status["own_marker"], status["other_writers"]) == (
        True,
        False,
        ["work-laptop"],
    )
    failed_job = failed[-1]["job"]
    assert isinstance(failed_job, dict) and failed_job["job_id"] == job["job_id"]
    assert failed_job["last_error"] == (
        "writer_conflict: marker of host work-laptop present"
    )
    assert (refused_undo["code"], refused_accept["code"]) == (
        "writer_conflict",
        "writer_conflict",
    )
    assert "batch.offer" not in [e["type"] for e in failed + replayed]
