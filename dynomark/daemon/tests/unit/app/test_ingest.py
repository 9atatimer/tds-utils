"""Behaviors row: A save is ingested (DYNOMARK.DESIGN.md, Behaviors and
Interfaces) -- ``ingest(bookmark, capture, *, store) -> Job``: "Given a
bookmark, When ingested, Then a Job is QUEUED; a second ingest with the same
(NodeId, Identity) returns the same job". Contract v1 keys the job on
(profile, node_id, identity of bookmark.url) (Delivery and replay).
"""

from dynomark_daemon.app.ingest import ingest
from dynomark_daemon.domain.bookmark import CaptureSource, Identity, Save
from dynomark_daemon.domain.ids import ProfileId
from dynomark_daemon.domain.job import JobState
from dynomark_daemon.testing.clock import FakeClock, SequentialIds
from dynomark_daemon.testing.store import InMemoryCorpusStore
from tests._factories import make_bookmark, make_capture

PROFILE = ProfileId("profile-a")


def test_ingest_a_new_save_queues_one_job_and_keeps_the_save() -> None:
    """Given a bookmark saved into Follow Up, When ingested, Then one QUEUED job
    for its normalized identity exists and its save is kept for processing."""
    store = InMemoryCorpusStore()
    bookmark = make_bookmark("HTTPS://Tokio.RS:443/tokio/tutorial")
    capture = make_capture("Tokio is an asynchronous runtime")

    job = ingest(
        bookmark,
        capture,
        PROFILE,
        store=store,
        clock=FakeClock(start_ms=1_000),
        ids=SequentialIds(),
    )

    assert (job.state, job.node_id, job.profile_id) == (
        JobState.QUEUED,
        bookmark.node_id,
        PROFILE,
    )
    assert job.identity == Identity("https://tokio.rs/tokio/tutorial")
    assert (job.attempts, job.seq, job.updated_at, job.backfill) == (0, 1, 1_000, False)
    assert store.list_jobs() == [job]
    assert store.get_save(job.job_id) == Save(bookmark=bookmark, capture=capture)


def test_ingest_twice_with_the_same_node_and_identity_returns_the_same_job() -> None:
    """Given an ingested save, When the same node is ingested again under
    another spelling of its URL, Then the same job is returned and nothing new
    is queued (requests are at-least-once)."""
    store = InMemoryCorpusStore()
    clock, ids = FakeClock(), SequentialIds()
    first = ingest(
        make_bookmark("https://tokio.rs/tokio/tutorial"),
        make_capture("text"),
        PROFILE,
        store=store,
        clock=clock,
        ids=ids,
    )

    again = ingest(
        make_bookmark("https://TOKIO.rs/tokio/./tutorial"),
        make_capture("", source=CaptureSource.NONE),
        PROFILE,
        store=store,
        clock=clock,
        ids=ids,
    )

    assert again == first
    assert store.list_jobs() == [first]
    save = store.get_save(first.job_id)
    assert save is not None and save.capture.text == "text"


def test_ingest_the_same_url_on_another_node_or_profile_is_another_job() -> None:
    """Given an ingested save, When the same URL is saved as another node, or
    the same node id arrives from another profile, Then each is its own job
    (node ids are per profile)."""
    store = InMemoryCorpusStore()
    clock, ids = FakeClock(), SequentialIds()
    first = ingest(
        make_bookmark(node_id="42"),
        make_capture(),
        PROFILE,
        store=store,
        clock=clock,
        ids=ids,
    )

    other_node = ingest(
        make_bookmark(node_id="43"),
        make_capture(),
        PROFILE,
        store=store,
        clock=clock,
        ids=ids,
    )
    other_profile = ingest(
        make_bookmark(node_id="42"),
        make_capture(),
        ProfileId("profile-b"),
        store=store,
        clock=clock,
        ids=ids,
    )

    assert len({first.job_id, other_node.job_id, other_profile.job_id}) == 3
    assert len(store.list_jobs()) == 3


def test_ingest_a_backfill_queues_a_job_marked_backfill() -> None:
    """Given a save the extension sends as backfill (contract v1, Jobs:
    Backfill), When ingested, Then its job is QUEUED and marked backfill."""
    store = InMemoryCorpusStore()

    job = ingest(
        make_bookmark(),
        make_capture(),
        PROFILE,
        backfill=True,
        store=store,
        clock=FakeClock(),
        ids=SequentialIds(),
    )

    assert (job.state, job.backfill) == (JobState.QUEUED, True)
