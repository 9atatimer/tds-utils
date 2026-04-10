import os
from datetime import datetime
from typing import List
from txtai.embeddings import Embeddings
from ..domain.models import LogEntry, SearchMatch
from ..domain.ports import SearchIndexPort

class TxtaiAdapter(SearchIndexPort):
    def __init__(self, index_path: str, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        """
        Initializes the txtai embeddings engine.
        index_path: Folder where the Faiss/SQLite index will live.
        model_name: The embedding model to use.
        """
        self.index_path = index_path
        self.embeddings = Embeddings({
            "path": model_name,
            "content": True  # This enables the SQLite backend for metadata
        })
        
        # Load index if it exists (txtai <8 used "config", >=8 uses "config.json")
        if os.path.exists(os.path.join(index_path, "config")) or \
           os.path.exists(os.path.join(index_path, "config.json")):
            self.embeddings.load(index_path)

    def add_entries(self, entries: List[LogEntry]):
        # Map domain objects to txtai's dictionary format.
        # NOTE: content=True is required by txtai for metadata storage, but
        # the "text" field is used ONLY for embedding generation -- txtai
        # does not persist the raw text when content=True, only the embeddings
        # and the metadata columns (path, timestamp, slug).
        # TODO(Task 2): Replace this with chunked full-file indexing -- each
        # log file will produce multiple chunks, each with its own embedding
        # and byte-offset metadata.
        documents = [
            {
                "id": entry.path,
                "text": f"{entry.slug or ''} {entry.content_sample or ''}",
                "path": entry.path,
                "timestamp": entry.timestamp.isoformat(),
                "slug": entry.slug
            }
            for entry in entries
        ]
        self.embeddings.index(documents)

    def search(self, query: str, limit: int = 5) -> List[SearchMatch]:
        results = self.embeddings.search(query, limit)
        matches = []
        for result in results:
            # txtai search with content=True returns dicts with id, text, score.
            # Metadata columns (path, timestamp, slug) may or may not be present
            # depending on txtai version. Fall back to id for path.
            path = result.get("path", result.get("id", ""))
            timestamp_str = result.get("timestamp")
            timestamp = (
                datetime.fromisoformat(timestamp_str)
                if timestamp_str
                else datetime.fromtimestamp(0)
            )
            entry = LogEntry(
                path=path,
                timestamp=timestamp,
                slug=result.get("slug"),
            )
            matches.append(SearchMatch(entry=entry, score=result["score"]))
        return matches

    def is_indexed(self, path: str) -> bool:
        # Check if the document ID exists in the index
        return self.embeddings.exists(path)

    def save(self):
        os.makedirs(self.index_path, mode=0o700, exist_ok=True)
        self.embeddings.save(self.index_path)
