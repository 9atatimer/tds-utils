"""A writer daemon over faked ports that has filed one job, shared by the
receipt and undo suites."""

from dynomark_daemon.app.file import file
from dynomark_daemon.app.receipt import ReceiptRecorded, receive_receipt
from dynomark_daemon.domain.batch import (
    BatchReceipt,
    OpApplied,
    WriteBatch,
)
from dynomark_daemon.domain.bookmark import Save
from dynomark_daemon.domain.events import BatchOffered
from dynomark_daemon.domain.ids import NodeId
from dynomark_daemon.domain.job import Job, JobState
from dynomark_daemon.domain.roles import HostRole
from dynomark_daemon.testing.clock import FakeClock, SequentialIds
from dynomark_daemon.testing.store import InMemoryCorpusStore
from tests._factories import (
    make_bookmark,
    make_capture,
    make_job,
    make_node,
    make_outline,
    make_outline_folder,
    make_path,
    make_placement,
    make_roots,
    make_tree,
)

RUST = make_path("Dynomark", "Rust")
ASYNC = make_path("Dynomark", "Rust", "Async")
TREE = make_tree(
    make_node("10", "1", "Follow Up"),
    make_node("11", "1", "Dynomark", index=1),
    make_node("14", "11", "Rust"),
    make_node("42", "10", "Tokio tutorial", url="https://tokio.rs/tokio/tutorial"),
)
CREATED = OpApplied(index=0, node_id=NodeId("16"), changed=True)
MOVED = OpApplied(index=1, node_id=NodeId("42"), changed=True)


class Daemon:
    """A writer that has filed one job into a new folder, Dynomark/Rust/Async."""

    def __init__(self) -> None:
        self.store = InMemoryCorpusStore()
        self.clock, self.ids = FakeClock(start_ms=1_000), SequentialIds()
        self.job = make_job(state=JobState.PLACED)
        self.store.put_job(self.job)
        self.store.put_save(
            self.job.job_id,
            Save(
                bookmark=make_bookmark(path=make_path("Follow Up")),
                capture=make_capture(),
            ),
        )
        self.store.put_tree_snapshot(TREE)
        batch = file(
            make_placement(folder=ASYNC),
            self.job,
            make_outline(make_outline_folder("Dynomark", "Rust", node_id="14")),
            make_roots(),
            HostRole.WRITER,
            store=self.store,
            clock=self.clock,
            ids=self.ids,
        )
        assert isinstance(batch, WriteBatch)
        self.batch = batch

    def receive(self, receipt: BatchReceipt) -> ReceiptRecorded:
        return receive_receipt(
            receipt, make_roots(), store=self.store, clock=self.clock, ids=self.ids
        )

    def job_now(self) -> Job:
        job = self.store.get_job(self.job.job_id)
        assert job is not None
        return job

    def offers(self) -> list[BatchOffered]:
        pending = self.store.unacked_events(self.job.profile_id)
        return [p.event for p in pending if isinstance(p.event, BatchOffered)]
