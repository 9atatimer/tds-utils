"""Use case: a question is answered with citations (DYNOMARK.DESIGN.md,
Behaviors and Interfaces; The daemon, "Chat"; Goal 5).

Retrieve the top-k entries with the same hybrid search tier 2 uses, answer
through ``CompletionPort``, then ground the draft in the domain: only
retrieved identities become ``Citation``s, other URLs are ``external``.
"""

from collections.abc import Sequence
from typing import Final

from dynomark_daemon.app.search import search_corpus
from dynomark_daemon.domain.bookmark import CorpusEntry, Identity, is_fetchable
from dynomark_daemon.domain.chat import Answer, Citation, Question, Turn, ground
from dynomark_daemon.domain.search import Query
from dynomark_daemon.ports.completion import CompletionPort
from dynomark_daemon.ports.embedding import EmbeddingPort
from dynomark_daemon.ports.store import CorpusStorePort

ASK_CONTEXT: Final = 8
"""How many retrieved entries (top-k) the completion is shown."""


def _retrieve(
    question: Question, *, store: CorpusStorePort, embedding: EmbeddingPort
) -> tuple[list[CorpusEntry], list[Citation]]:
    hits = search_corpus(Query(question.text), store=store, embedding=embedding)
    entries: list[CorpusEntry] = []
    citations: list[Citation] = []
    for hit in hits[:ASK_CONTEXT]:
        entry = store.get_entry(hit.identity)
        if entry is not None:
            entries.append(entry)
            citations.append(Citation(hit.identity, hit.title, hit.path))
    return entries, citations


def ask(
    question: Question,
    history: Sequence[Turn],
    *,
    store: CorpusStorePort,
    embedding: EmbeddingPort,
    completion: CompletionPort,
) -> Answer:
    """The grounded answer to ``question`` after ``history`` (oldest first).

    Raises:
        PortError: the embedding or completion call failed.
    """
    entries, retrieved = _retrieve(question, store=store, embedding=embedding)
    draft = completion.answer(question, history=history, context=entries)
    mentioned = {Identity.from_url(url) for url in draft.urls if is_fetchable(url)}
    in_corpus = frozenset(i for i in mentioned if store.get_entry(i) is not None)
    return ground(draft, retrieved, in_corpus=in_corpus)
