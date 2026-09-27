"""Goal 4, tier 2 (DYNOMARK.DESIGN.md): "tier-2 hits arrive within 500 ms
(P95)", measured as the daemon's share -- the fused search over the real
SQLite store at 10,000 entries of 768-dimension embeddings -- with a free
embedding call (a local model's embed time is the model's, not the
daemon's).

The claim is about this code on a machine able to run it. Each sample is
taken right after a fixed CPU workload; when that workload is itself over
its budget the runner is too slow (or too busy) at that moment to measure
the goal, and the test is skipped rather than failed.
"""

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest

from dynomark_daemon.adapters.sqlite_store import SqliteCorpusStore
from dynomark_daemon.app.search import search_corpus
from dynomark_daemon.domain.search import Query
from dynomark_daemon.testing.embedding import HashingEmbedding
from tests._factories import make_entry

pytestmark = pytest.mark.integration

ENTRIES: Final = 10_000
DIMENSIONS: Final = 768
BUDGET_MS: Final = 500.0
SAMPLES: Final = 20
CALIBRATION_BUDGET_MS: Final = 60.0
"""The fixed workload's P95, taken between searches, on a runner fit to
measure the goal: where it was checked (Python 3.11) it was about 50 ms with
the search P95 about 350 ms, so a runner at this budget would search in
about 410 ms."""
WORDS: Final = (
    "async rust tokio serde python kernel bookmarks design review garden cloud budget"
).split()
QUERIES: Final = ("tokio", "async rust", "serde notes", "garden 42", "budget cloud")


def _word(i: int, k: int) -> str:
    return WORDS[(i * 7 + k * 3) % len(WORDS)]


@pytest.fixture(scope="module")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> Iterator[SqliteCorpusStore]:
    path = Path(tmp_path_factory.mktemp("latency")) / "corpus.sqlite3"
    store = SqliteCorpusStore.open(path)
    embedding = HashingEmbedding(dimensions=DIMENSIONS)
    for i in range(ENTRIES):
        text = f"{_word(i, 3)} {_word(i, 4)} page {i} " * 20
        store.put_entry(
            make_entry(
                f"https://e{i}.example/",
                title=f"{_word(i, 0)} {_word(i, 1)} notes {i}",
                summary=f"About {_word(i, 2)}.",
                text=text,
                vector=embedding.embed(text).vector,
            )
        )
    try:
        yield store
    finally:
        store.close()


def _calibration_ms() -> float:
    a = [float(i % 13) for i in range(DIMENSIONS)]
    b = [float(i % 7) for i in range(DIMENSIONS)]
    start = time.perf_counter()
    total = 0.0
    for _ in range(1_000):
        total += sum(x * y for x, y in zip(a, b, strict=True))
    if total == 0.0:
        raise AssertionError("unreachable: the calibration result is used")
    return (time.perf_counter() - start) * 1000


def _p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    return ordered[max(0, -(-len(ordered) * 95 // 100) - 1)]


def test_tier2_hits_arrive_within_500_ms_p95_at_10000_entries(
    corpus: SqliteCorpusStore,
) -> None:
    """Given 10,000 entries in the SQLite store, When tier-2 queries run, Then
    the P95 time to the fused hits is within 500 ms (skipped on a runner
    too slow to measure it)."""
    embedding = HashingEmbedding(dimensions=DIMENSIONS)
    search_corpus(Query(QUERIES[0]), store=corpus, embedding=embedding)  # warm-up
    searches: list[float] = []
    calibrations: list[float] = []
    for i in range(SAMPLES):
        calibrations.append(_calibration_ms())
        start = time.perf_counter()
        hits = search_corpus(
            Query(QUERIES[i % len(QUERIES)]), store=corpus, embedding=embedding
        )
        searches.append((time.perf_counter() - start) * 1000)
        assert hits

    observed, calibration = _p95(searches), _p95(calibrations)
    print(f"tier-2 P95 {observed:.1f} ms, calibration P95 {calibration:.1f} ms")
    if observed > BUDGET_MS and calibration > CALIBRATION_BUDGET_MS:
        pytest.skip(
            f"runner too slow to measure Goal 4 tier 2: P95 {observed:.0f} ms, "
            f"calibration P95 {calibration:.0f} ms over {CALIBRATION_BUDGET_MS} ms"
        )
    assert observed <= BUDGET_MS
