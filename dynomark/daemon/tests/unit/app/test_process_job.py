"""Behaviors rows: A job is processed to an entry; A failed enrichment is
retried, then parked; and the job half of Content falls back to fetch
(DYNOMARK.DESIGN.md, Behaviors and Interfaces) --
``process_job(job, *, store, embedding, completion) -> CorpusEntry``.

The daemon side needs more than the design's signature names: the
``RetryPolicy`` value, the fetch ``ContentSourcePort`` for the capture
fallback, and a ``Clock``.
"""

from dynomark_daemon.app.ingest import ingest
from dynomark_daemon.app.process import process_job
from dynomark_daemon.app.search import search_corpus
from dynomark_daemon.domain.bookmark import (
    Capture,
    CaptureSource,
    CorpusEntry,
    Enrichment,
    Identity,
)
from dynomark_daemon.domain.ids import ProfileId
from dynomark_daemon.domain.job import Job, JobState, RetryPolicy
from dynomark_daemon.domain.search import HitTier, Query
from dynomark_daemon.testing.clock import FakeClock, SequentialIds
from dynomark_daemon.testing.completion import ScriptedCompletion
from dynomark_daemon.testing.content import FakeFetch
from dynomark_daemon.testing.embedding import HashingEmbedding
from dynomark_daemon.testing.store import InMemoryCorpusStore
from tests._factories import make_bookmark, make_capture

URL = "https://tokio.rs/tokio/tutorial"
POLICY = RetryPolicy(attempts=3, initial_backoff_ms=1_000, max_backoff_ms=60_000)
ENRICHMENT = Enrichment(summary="An async runtime for Rust.", tags=("rust", "async"))


def _queued(store: InMemoryCorpusStore, capture: Capture) -> Job:
    return ingest(
        make_bookmark(URL),
        capture,
        ProfileId("profile-a"),
        store=store,
        clock=FakeClock(),
        ids=SequentialIds(),
    )


def test_process_job_with_a_capture_makes_an_entry_with_summary_tags_embedding() -> (
    None
):
    """Given a queued job whose save carries a tab capture, When processed, Then
    the entry has summary, tags and an embedding, is stored, and the job is
    ENRICHED with capture source tab."""
    store = InMemoryCorpusStore()
    job = _queued(store, make_capture("Tokio schedules green threads"))

    result = process_job(
        job,
        POLICY,
        store=store,
        content=FakeFetch({}),
        embedding=HashingEmbedding(),
        completion=ScriptedCompletion(enrich=[ENRICHMENT]),
        clock=FakeClock(start_ms=5_000),
    )

    assert isinstance(result, CorpusEntry)
    assert (result.summary, result.tags) == (ENRICHMENT.summary, ENRICHMENT.tags)
    assert result.embedding.model_id == "fake:hashing"
    assert result.identity == Identity(URL)
    assert store.get_entry(Identity(URL)) == result
    stored = store.get_job(job.job_id)
    assert stored is not None
    assert (stored.state, stored.capture_source) == (
        JobState.ENRICHED,
        CaptureSource.TAB,
    )


def test_search_corpus_finds_a_word_only_in_the_captured_text() -> None:
    """Given a processed job whose captured text alone holds a word, When
    search_corpus is queried for it, Then that entry is a corpus hit (Goal 4)."""
    store = InMemoryCorpusStore()
    job = _queued(store, make_capture("the reactor drives epoll readiness"))
    process_job(
        job,
        POLICY,
        store=store,
        content=FakeFetch({}),
        embedding=HashingEmbedding(),
        completion=ScriptedCompletion(enrich=[ENRICHMENT]),
        clock=FakeClock(),
    )

    hits = search_corpus(Query("epoll"), store=store, embedding=HashingEmbedding())

    assert [hit.identity for hit in hits][:1] == [Identity(URL)]
    assert hits[0].tier is HitTier.CORPUS


def test_process_job_without_a_capture_fetches_the_page() -> None:
    """Given a save ingested with capture source none, When processed, Then the
    page is fetched and the entry is built from the fetched text (source
    fetch)."""
    store = InMemoryCorpusStore()
    job = _queued(store, Capture.none())

    result = process_job(
        job,
        POLICY,
        store=store,
        content=FakeFetch({URL: ("Tokio", "fetched words")}),
        embedding=HashingEmbedding(),
        completion=ScriptedCompletion(enrich=[ENRICHMENT]),
        clock=FakeClock(),
    )

    assert isinstance(result, CorpusEntry)
    assert (result.capture.source, result.capture.text) == (
        CaptureSource.FETCH,
        "fetched words",
    )
    stored = store.get_job(job.job_id)
    assert stored is not None and stored.capture_source is CaptureSource.FETCH


def test_process_job_whose_fetch_fails_continues_with_source_none() -> None:
    """Given a save with capture source none whose page cannot be fetched, When
    processed, Then the job still reaches ENRICHED with capture source none."""
    store = InMemoryCorpusStore()
    job = _queued(store, Capture.none())

    result = process_job(
        job,
        POLICY,
        store=store,
        content=FakeFetch({}),
        embedding=HashingEmbedding(),
        completion=ScriptedCompletion(enrich=[ENRICHMENT]),
        clock=FakeClock(),
    )

    assert isinstance(result, CorpusEntry)
    stored = store.get_job(job.job_id)
    assert stored is not None
    assert (stored.state, stored.capture_source) == (
        JobState.ENRICHED,
        CaptureSource.NONE,
    )
