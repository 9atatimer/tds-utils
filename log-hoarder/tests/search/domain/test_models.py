"""Tests for Span and Chunk domain models."""

import pytest

from search.domain.models import Chunk, Span


# --- Span construction ---


class TestSpanConstruction:
    """Span is a value object representing a logically coherent segment of a session."""

    def test_create_span_with_required_fields(self) -> None:
        """Given valid required fields, When creating a Span, Then all fields are set."""
        span = Span(
            session_path="/logs/archived/mysession/0/0",
            span_id=0,
            byte_start=0,
            byte_end=4096,
        )

        assert span.session_path == "/logs/archived/mysession/0/0"
        assert span.span_id == 0
        assert span.byte_start == 0
        assert span.byte_end == 4096
        assert span.working_dir is None

    def test_create_span_with_working_dir(self) -> None:
        """Given a working directory, When creating a Span, Then working_dir is set."""
        span = Span(
            session_path="/logs/archived/s/0/0",
            span_id=1,
            byte_start=4096,
            byte_end=8192,
            working_dir="/home/user/project",
        )

        assert span.working_dir == "/home/user/project"

    def test_span_is_frozen(self) -> None:
        """Given a Span, When mutating a field, Then it raises an error."""
        span = Span(
            session_path="/logs/s/0/0",
            span_id=0,
            byte_start=0,
            byte_end=100,
        )

        with pytest.raises(AttributeError):
            span.span_id = 5  # type: ignore[misc]


# --- Span validation ---


class TestSpanValidation:
    """Span enforces invariants on byte ranges and IDs."""

    def test_create_span_negative_span_id_raises(self) -> None:
        """Given a negative span_id, When creating a Span, Then it raises ValueError."""
        with pytest.raises(ValueError, match="span_id"):
            Span(
                session_path="/logs/s/0/0",
                span_id=-1,
                byte_start=0,
                byte_end=100,
            )

    def test_create_span_byte_end_not_greater_than_start_raises(self) -> None:
        """Given byte_end <= byte_start, When creating a Span, Then it raises ValueError."""
        with pytest.raises(ValueError, match="byte_end"):
            Span(
                session_path="/logs/s/0/0",
                span_id=0,
                byte_start=100,
                byte_end=100,
            )

    def test_create_span_negative_byte_start_raises(self) -> None:
        """Given a negative byte_start, When creating a Span, Then it raises ValueError."""
        with pytest.raises(ValueError, match="byte_start"):
            Span(
                session_path="/logs/s/0/0",
                span_id=0,
                byte_start=-1,
                byte_end=100,
            )

    def test_create_span_empty_session_path_raises(self) -> None:
        """Given an empty session_path, When creating a Span, Then it raises ValueError."""
        with pytest.raises(ValueError, match="session_path"):
            Span(
                session_path="",
                span_id=0,
                byte_start=0,
                byte_end=100,
            )


# --- Span computed properties ---


class TestSpanProperties:
    """Span exposes useful derived values."""

    def test_span_length(self) -> None:
        """Given a Span, When accessing length, Then it returns byte_end - byte_start."""
        span = Span(
            session_path="/logs/s/0/0",
            span_id=0,
            byte_start=100,
            byte_end=600,
        )

        assert span.length == 500


# --- Chunk construction ---


class TestChunkConstruction:
    """Chunk is a value object representing an embedding-sized piece of a Span."""

    def test_create_chunk_with_required_fields(self) -> None:
        """Given valid fields, When creating a Chunk, Then all fields are set."""
        chunk = Chunk(
            session_path="/logs/archived/mysession/0/0",
            span_id=0,
            chunk_index=0,
            byte_start=0,
            byte_end=512,
            text="some cleaned text for embedding",
        )

        assert chunk.session_path == "/logs/archived/mysession/0/0"
        assert chunk.span_id == 0
        assert chunk.chunk_index == 0
        assert chunk.byte_start == 0
        assert chunk.byte_end == 512
        assert chunk.text == "some cleaned text for embedding"

    def test_chunk_is_frozen(self) -> None:
        """Given a Chunk, When mutating a field, Then it raises an error."""
        chunk = Chunk(
            session_path="/logs/s/0/0",
            span_id=0,
            chunk_index=0,
            byte_start=0,
            byte_end=100,
            text="hello",
        )

        with pytest.raises(AttributeError):
            chunk.text = "nope"  # type: ignore[misc]


# --- Chunk validation ---


class TestChunkValidation:
    """Chunk enforces invariants on byte ranges, IDs, and text."""

    def test_create_chunk_negative_chunk_index_raises(self) -> None:
        """Given a negative chunk_index, When creating a Chunk, Then it raises ValueError."""
        with pytest.raises(ValueError, match="chunk_index"):
            Chunk(
                session_path="/logs/s/0/0",
                span_id=0,
                chunk_index=-1,
                byte_start=0,
                byte_end=100,
                text="hello",
            )

    def test_create_chunk_negative_span_id_raises(self) -> None:
        """Given a negative span_id, When creating a Chunk, Then it raises ValueError."""
        with pytest.raises(ValueError, match="span_id"):
            Chunk(
                session_path="/logs/s/0/0",
                span_id=-1,
                chunk_index=0,
                byte_start=0,
                byte_end=100,
                text="hello",
            )

    def test_create_chunk_byte_end_not_greater_than_start_raises(self) -> None:
        """Given byte_end <= byte_start, When creating a Chunk, Then it raises ValueError."""
        with pytest.raises(ValueError, match="byte_end"):
            Chunk(
                session_path="/logs/s/0/0",
                span_id=0,
                chunk_index=0,
                byte_start=50,
                byte_end=50,
                text="hello",
            )

    def test_create_chunk_empty_text_raises(self) -> None:
        """Given empty text, When creating a Chunk, Then it raises ValueError."""
        with pytest.raises(ValueError, match="text"):
            Chunk(
                session_path="/logs/s/0/0",
                span_id=0,
                chunk_index=0,
                byte_start=0,
                byte_end=100,
                text="",
            )

    def test_create_chunk_whitespace_only_text_raises(self) -> None:
        """Given whitespace-only text, When creating a Chunk, Then it raises ValueError."""
        with pytest.raises(ValueError, match="text"):
            Chunk(
                session_path="/logs/s/0/0",
                span_id=0,
                chunk_index=0,
                byte_start=0,
                byte_end=100,
                text="   \n\t  ",
            )

    def test_create_chunk_empty_session_path_raises(self) -> None:
        """Given an empty session_path, When creating a Chunk, Then it raises ValueError."""
        with pytest.raises(ValueError, match="session_path"):
            Chunk(
                session_path="",
                span_id=0,
                chunk_index=0,
                byte_start=0,
                byte_end=100,
                text="hello",
            )


# --- Chunk computed properties ---


class TestChunkProperties:
    """Chunk exposes useful derived values."""

    def test_chunk_length(self) -> None:
        """Given a Chunk, When accessing length, Then it returns byte_end - byte_start."""
        chunk = Chunk(
            session_path="/logs/s/0/0",
            span_id=0,
            chunk_index=0,
            byte_start=100,
            byte_end=600,
            text="some text",
        )

        assert chunk.length == 500

    def test_chunk_index_key(self) -> None:
        """Given a Chunk, When accessing index_key, Then it returns session:span:chunk format."""
        chunk = Chunk(
            session_path="/logs/archived/mysession/0/0",
            span_id=2,
            chunk_index=5,
            byte_start=0,
            byte_end=100,
            text="some text",
        )

        assert chunk.index_key == "/logs/archived/mysession/0/0:2:5"


# --- Span/Chunk relationship ---


class TestSpanChunkRelationship:
    """Chunk.from_span factory ensures chunk byte range is within span bounds."""

    def test_from_span_valid_range(self) -> None:
        """Given a Span and valid sub-range, When calling Chunk.from_span, Then chunk is created."""
        span = Span(
            session_path="/logs/s/0/0",
            span_id=3,
            byte_start=1000,
            byte_end=5000,
        )

        chunk = Chunk.from_span(
            span=span,
            chunk_index=0,
            byte_start=1000,
            byte_end=2000,
            text="cleaned text",
        )

        assert chunk.session_path == span.session_path
        assert chunk.span_id == span.span_id
        assert chunk.byte_start == 1000
        assert chunk.byte_end == 2000

    def test_from_span_chunk_exceeds_span_raises(self) -> None:
        """Given chunk byte_end > span byte_end, When calling from_span, Then it raises ValueError."""
        span = Span(
            session_path="/logs/s/0/0",
            span_id=0,
            byte_start=0,
            byte_end=1000,
        )

        with pytest.raises(ValueError, match="span"):
            Chunk.from_span(
                span=span,
                chunk_index=0,
                byte_start=0,
                byte_end=1500,
                text="too far",
            )

    def test_from_span_chunk_starts_before_span_raises(self) -> None:
        """Given chunk byte_start < span byte_start, When calling from_span, Then it raises ValueError."""
        span = Span(
            session_path="/logs/s/0/0",
            span_id=0,
            byte_start=500,
            byte_end=1000,
        )

        with pytest.raises(ValueError, match="span"):
            Chunk.from_span(
                span=span,
                chunk_index=0,
                byte_start=400,
                byte_end=800,
                text="too early",
            )
