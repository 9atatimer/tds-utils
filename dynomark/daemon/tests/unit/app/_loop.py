"""A daemon's job loop over faked ports, shared by the run_job suites."""

from dynomark_daemon.app.ingest import ingest
from dynomark_daemon.app.run import run_job
from dynomark_daemon.domain.bookmark import Enrichment
from dynomark_daemon.domain.ids import ProfileId
from dynomark_daemon.domain.job import Job, RetryPolicy
from dynomark_daemon.domain.roles import HostRole
from dynomark_daemon.domain.tree import FolderPath, Snapshot
from dynomark_daemon.domain.writer import WriterConflict
from dynomark_daemon.testing.clock import FakeClock, SequentialIds
from dynomark_daemon.testing.completion import ScriptedCompletion
from dynomark_daemon.testing.content import FakeFetch
from dynomark_daemon.testing.embedding import HashingEmbedding
from dynomark_daemon.testing.store import InMemoryCorpusStore
from tests._factories import (
    make_bookmark,
    make_capture,
    make_node,
    make_path,
    make_roots,
    make_tree,
)

PROFILE = ProfileId("profile-a")
URL = "https://tokio.rs/tokio/tutorial"
POLICY = RetryPolicy(attempts=3, initial_backoff_ms=1_000, max_backoff_ms=60_000)
RUST = make_path("Dynomark", "Rust")
TREE = make_tree(
    make_node("10", "1", "Follow Up"),
    make_node("11", "1", "Dynomark", index=1),
    make_node("14", "11", "Rust"),
    make_node("42", "10", "Tokio tutorial", url="https://tokio.rs/tokio/tutorial"),
)
ENRICHMENT = Enrichment(summary="An async runtime.", tags=("rust",))


class Loop:
    """One daemon's ports, faked, and the job loop's step over them."""

    def __init__(self, completion: ScriptedCompletion, tree: Snapshot | None) -> None:
        self.store = InMemoryCorpusStore()
        self.completion = completion
        self.clock, self.ids = FakeClock(start_ms=1_000), SequentialIds()
        if tree is not None:
            self.store.put_tree_snapshot(tree)

    def save(self, path: FolderPath | None = None, *, backfill: bool = False) -> Job:
        return ingest(
            make_bookmark(path=path or make_path("Follow Up")),
            make_capture("Tokio schedules tasks"),
            PROFILE,
            backfill=backfill,
            store=self.store,
            clock=self.clock,
            ids=self.ids,
        )

    def run(
        self,
        job: Job,
        role: HostRole = HostRole.WRITER,
        *,
        conflict: WriterConflict | None = None,
    ) -> Job:
        current = self.store.get_job(job.job_id)
        assert current is not None
        return run_job(
            current,
            role,
            make_roots(),
            POLICY,
            store=self.store,
            content=FakeFetch({}),
            embedding=HashingEmbedding(),
            completion=self.completion,
            clock=self.clock,
            ids=self.ids,
            conflict=conflict,
        )

    def events(self) -> list[object]:
        return [p.event for p in self.store.unacked_events(PROFILE)]
