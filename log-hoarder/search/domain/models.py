"""Domain models for log-hoarder semantic search."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class LogEntry:
    path: str
    timestamp: datetime
    slug: str | None = None
    content_sample: str | None = None


@dataclass
class SearchMatch:
    entry: LogEntry
    score: float


@dataclass(frozen=True, slots=True)
class Span:
    """A logically coherent segment of a terminal session.

    Byte offsets reference uncompressed log content.
    """

    session_path: str
    span_id: int
    byte_start: int
    byte_end: int
    working_dir: str | None = None

    def __post_init__(self) -> None:
        if not self.session_path:
            raise ValueError("session_path must not be empty")
        if self.span_id < 0:
            raise ValueError("span_id must be non-negative")
        if self.byte_start < 0:
            raise ValueError("byte_start must be non-negative")
        if self.byte_end <= self.byte_start:
            raise ValueError("byte_end must be greater than byte_start")

    @property
    def length(self) -> int:
        return self.byte_end - self.byte_start


@dataclass(frozen=True, slots=True)
class Chunk:
    """An embedding-sized piece of a Span.

    Byte offsets reference uncompressed log content.
    The text field holds cleaned content for embedding — it is not stored in
    the index, only passed through the indexing pipeline.
    """

    session_path: str
    span_id: int
    chunk_index: int
    byte_start: int
    byte_end: int
    text: str

    def __post_init__(self) -> None:
        if not self.session_path:
            raise ValueError("session_path must not be empty")
        if self.span_id < 0:
            raise ValueError("span_id must be non-negative")
        if self.chunk_index < 0:
            raise ValueError("chunk_index must be non-negative")
        if self.byte_start < 0:
            raise ValueError("byte_start must be non-negative")
        if self.byte_end <= self.byte_start:
            raise ValueError("byte_end must be greater than byte_start")
        if not self.text.strip():
            raise ValueError("text must not be empty or whitespace-only")

    @property
    def length(self) -> int:
        return self.byte_end - self.byte_start

    @property
    def index_key(self) -> str:
        """The composite key used to identify this chunk in the index."""
        return f"{self.session_path}:{self.span_id}:{self.chunk_index}"

    @classmethod
    def from_span(
        cls,
        *,
        span: Span,
        chunk_index: int,
        byte_start: int,
        byte_end: int,
        text: str,
    ) -> Chunk:
        """Create a Chunk whose byte range is validated against a parent Span."""
        if byte_start < span.byte_start or byte_end > span.byte_end:
            raise ValueError(
                f"Chunk byte range [{byte_start}:{byte_end}) falls outside "
                f"span [{span.byte_start}:{span.byte_end})"
            )
        return cls(
            session_path=span.session_path,
            span_id=span.span_id,
            chunk_index=chunk_index,
            byte_start=byte_start,
            byte_end=byte_end,
            text=text,
        )
