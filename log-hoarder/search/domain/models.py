from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List

@dataclass
class LogEntry:
    path: str
    timestamp: datetime
    slug: Optional[str] = None
    content_sample: Optional[str] = None

@dataclass
class SearchMatch:
    entry: LogEntry
    score: float
