"""Use case: the corpus is re-embedded after an embedding model change
(DYNOMARK.DESIGN.md, Data Model: ``corpus_entry.embedding`` records the
model that produced it; Key Decisions, Weakened rules restored 2026-10-16;
issue #423).

KNN compares only vectors of the current model, so an entry another model
embedded is found by full-text search alone until it is re-embedded here.
The job loop runs this in the background, a bounded batch per pass; each
entry is re-embedded from what it was first embedded from (title, summary,
tags), with no model call but the embedding's.
"""

from dataclasses import replace

from dynomark_daemon.domain.bookmark import Enrichment, embedding_text
from dynomark_daemon.ports.embedding import EmbeddingPort
from dynomark_daemon.ports.store import CorpusStorePort


def reembed_corpus(
    *, store: CorpusStorePort, embedding: EmbeddingPort, limit: int
) -> int:
    """Re-embed up to ``limit`` entries some other model embedded; how many.

    Raises:
        EmbeddingError: the embedding model could not embed; the entries not
            reached keep their old vectors for a later pass.
    """
    model_id = embedding.model().model_id
    stale = store.entries_embedded_otherwise(model_id, limit=limit)
    for entry in stale:
        about = Enrichment(summary=entry.summary, tags=entry.tags)
        vector = embedding.embed(embedding_text(entry.bookmark, about))
        with store.atomic():
            # No unit of work spans the model call: a fresh enrichment, or
            # retention, may have replaced or dropped the entry meanwhile;
            # only the entry this vector was made from is replaced.
            if store.get_entry(entry.identity) == entry:
                store.put_entry(replace(entry, embedding=vector))
    return len(stale)
