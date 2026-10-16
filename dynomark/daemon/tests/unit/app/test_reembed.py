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
