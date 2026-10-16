"""``corpus_entry.embedding`` records the model that produced it, and the
corpus is searched in one model's space (DYNOMARK.DESIGN.md, Data Model;
issue #423): KNN reads only entries of the current embedding model, and a
model change re-embeds the corpus in the background, through the job loop.

``reembed_corpus(*, store, embedding, limit) -> int`` re-embeds up to
``limit`` entries some other model embedded, from what each was embedded
from (title, summary, tags).
"""

from dataclasses import replace

from dynomark_daemon.app.reembed import reembed_corpus
from dynomark_daemon.app.search import search_corpus
from dynomark_daemon.domain.bookmark import Embedding, Enrichment, embedding_text
from dynomark_daemon.domain.config import ModelInfo
from dynomark_daemon.domain.search import Query
from dynomark_daemon.testing.embedding import HashingEmbedding
from dynomark_daemon.testing.store import InMemoryCorpusStore
from tests._factories import make_entry

OLD = "old:model"


def _old(url: str, *, title: str) -> InMemoryCorpusStore:
    store = InMemoryCorpusStore()
    entry = make_entry(url, title=title, summary="a runtime", tags=("rust",))
    store.put_entry(replace(entry, embedding=Embedding((1.0, 0.0), OLD)))
    return store


def test_search_never_returns_an_entry_by_another_models_vector() -> None:
    """Given an entry embedded by an old model and sharing no word with the
    query, When searched, Then it is no hit: its vector is in another space
    and is never compared."""
    store = _old("https://tokio.rs/", title="Tokio")

    hits = search_corpus(Query("cooking"), store=store, embedding=HashingEmbedding())

    assert hits == []


def test_reembed_corpus_moves_old_entries_into_the_current_model() -> None:
    """Given entries embedded by an old model, When re-embedded with a limit of
    one, Then one entry is re-embedded per call, from its title, summary and
    tags, until none is left; the rest of each entry is unchanged."""
    store = _old("https://tokio.rs/", title="Tokio")
    other = make_entry("https://smol.rs/", title="smol")
    store.put_entry(replace(other, embedding=Embedding((1.0, 0.0), OLD)))
    embedding = HashingEmbedding()

    counts = [
        reembed_corpus(store=store, embedding=embedding, limit=1) for _ in range(3)
    ]

    assert counts == [1, 1, 0]
    entry = store.get_entry(make_entry("https://tokio.rs/").identity)
    assert entry is not None
    about = Enrichment(summary="a runtime", tags=("rust",))
    assert entry.embedding == embedding.embed(embedding_text(entry.bookmark, about))
    assert (entry.summary, entry.tags) == ("a runtime", ("rust",))


class _ReplacedDuringEmbed:
    """An EmbeddingPort over HashingEmbedding whose model call is where a
    fresh enrichment (or retention) changes the entry being re-embedded."""

    def __init__(self, store: InMemoryCorpusStore, url: str, *, drop: bool) -> None:
        self._inner = HashingEmbedding()
        self._store = store
        self._url = url
        self._drop = drop

    def model(self) -> ModelInfo:
        return self._inner.model()

    def embed(self, text: str) -> Embedding:
        identity = make_entry(self._url).identity
        if self._drop:
            self._store.drop_entry(identity)
        else:
            fresh = make_entry(self._url, title="Tokio", summary="fresh enrichment")
            self._store.put_entry(fresh)
        return self._inner.embed(text)


def test_an_entry_replaced_while_it_is_re_embedded_keeps_the_fresher_entry() -> None:
    """Given an old-model entry, When a fresh enrichment replaces it while its
    re-embedding is at the model, Then the stale vector is not written over
    the fresher entry: it keeps its own summary and embedding (issue #534
    T14)."""
    url = "https://tokio.rs/"
    store = _old(url, title="Tokio")
    embedding = _ReplacedDuringEmbed(store, url, drop=False)

    reembed_corpus(store=store, embedding=embedding, limit=10)

    entry = store.get_entry(make_entry(url).identity)
    assert entry == make_entry(url, title="Tokio", summary="fresh enrichment")


def test_an_entry_dropped_while_it_is_re_embedded_stays_dropped() -> None:
    """Given an old-model entry, When retention drops it while its re-embedding
    is at the model, Then re-embedding does not bring it back."""
    url = "https://tokio.rs/"
    store = _old(url, title="Tokio")

    reembed_corpus(
        store=store, embedding=_ReplacedDuringEmbed(store, url, drop=True), limit=10
    )

    assert store.get_entry(make_entry(url).identity) is None
