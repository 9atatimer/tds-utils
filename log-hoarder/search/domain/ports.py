from abc import ABC, abstractmethod
from typing import List
from .models import LogEntry, SearchMatch

class SearchIndexPort(ABC):
    @abstractmethod
    def add_entries(self, entries: List[LogEntry]):
        """Index multiple log entries."""
        pass

    @abstractmethod
    def search(self, query: str, limit: int = 5) -> List[SearchMatch]:
        """Perform semantic search for a query string."""
        pass

    @abstractmethod
    def is_indexed(self, path: str) -> bool:
        """Check if a log path is already in the index."""
        pass

    @abstractmethod
    def save(self):
        """Persist index to disk."""
        pass
