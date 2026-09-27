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
    Embedding,
    Enrichment,
    Identity,
)
from dynomark_daemon.domain.ids import ProfileId
from dynomark_daemon.domain.job import Job, JobState, RetryPolicy
from dynomark_daemon.domain.search import HitTier, Query
from dynomark_daemon.ports.completion import CompletionError
from dynomark_daemon.ports.embedding import EmbeddingError
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


def _process(
    store: InMemoryCorpusStore, job: Job, completion: ScriptedCompletion
) -> CorpusEntry | Job:
    stored = store.get_job(job.job_id)
    assert stored is not None
    return process_job(
        stored,
        POLICY,
        store=store,
        content=FakeFetch({}),
        embedding=HashingEmbedding(),
        completion=completion,
        clock=FakeClock(),
    )


def test_process_job_whose_enrichment_always_errors_fails_after_policy_attempts() -> (
    None
):
    """Given a completion that errors RetryPolicy.attempts times, When the job
    is processed that many times, Then it waits for a retry until the last
    attempt, is then FAILED with the error, and no write batch references its
    identity."""
    store = InMemoryCorpusStore()
    job = _queued(store, make_capture("text"))
    down = CompletionError("completion: connection refused", retryable=True)
    completion = ScriptedCompletion(enrich=[down] * POLICY.attempts)

    results = [_process(store, job, completion) for _ in range(POLICY.attempts)]

    assert [r.state for r in results if isinstance(r, Job)] == [
        JobState.CAPTURING,
        JobState.CAPTURING,
        JobState.FAILED,
    ]
    failed = store.get_job(job.job_id)
    assert failed is not None
    assert (failed.state, failed.attempts) == (JobState.FAILED, POLICY.attempts)
    assert failed.last_error == "completion: connection refused"
    assert store.get_entry(job.identity) is None
    assert [b for b in store.list_batches() if b.identity == job.identity] == []


def test_process_job_after_one_transient_error_succeeds_on_the_retry() -> None:
    """Given a completion that errors once then answers, When the job is
    processed twice, Then the first attempt leaves it for a retry and the
    second yields the entry."""
    store = InMemoryCorpusStore()
    job = _queued(store, make_capture("text"))
    completion = ScriptedCompletion(
        enrich=[CompletionError("model loading", retryable=True), ENRICHMENT]
    )

    first = _process(store, job, completion)
    second = _process(store, job, completion)

    assert isinstance(first, Job) and first.attempts == 1
    assert isinstance(second, CorpusEntry)
    stored = store.get_job(job.job_id)
    assert stored is not None and stored.state is JobState.ENRICHED


def test_process_job_with_a_non_retryable_error_fails_at_once() -> None:
    """Given a completion error that is not retryable, When processed, Then the
    job is FAILED after one attempt."""
    store = InMemoryCorpusStore()
    job = _queued(store, make_capture("text"))
    completion = ScriptedCompletion(
        enrich=[CompletionError("model refused the input", retryable=False)]
    )

    result = _process(store, job, completion)

    assert isinstance(result, Job)
    assert (result.state, result.attempts) == (JobState.FAILED, 1)


def test_process_job_whose_embedding_errors_is_retried_like_enrichment() -> None:
    """Given an embedding port that errors, When processed, Then the attempt is
    counted like a completion error (both are enrichment)."""
    store = InMemoryCorpusStore()
    job = _queued(store, make_capture("text"))

    result = process_job(
        job,
        POLICY,
        store=store,
        content=FakeFetch({}),
        embedding=_BrokenEmbedding(),
        completion=ScriptedCompletion(enrich=[ENRICHMENT]),
        clock=FakeClock(),
    )

    assert isinstance(result, Job)
    assert (result.state, result.attempts) == (JobState.CAPTURING, 1)


class _BrokenEmbedding(HashingEmbedding):
    def embed(self, text: str) -> Embedding:
        raise EmbeddingError("embedding: timeout", retryable=True)
