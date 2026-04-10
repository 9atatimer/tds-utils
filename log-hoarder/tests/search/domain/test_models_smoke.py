"""Smoke tests: Span and Chunk models against realistic log-hoarder session data.

These tests use paths, sizes, and content patterns drawn from real archived
session logs to verify the domain models work with production-shaped data.
"""

import pytest

from search.domain.models import Chunk, Span


# --- Real session path formats ---

# Actual archived layout: $TDS_LOG_DIR/archived/SESSION/WINDOW/PANE/HHMMSS.log
REAL_PATHS = [
    "/Users/stumpf/.local/share/log-hoarder/archived/0/0/0",
    "/Users/stumpf/.local/share/log-hoarder/archived/1/0/0",
    "/Users/stumpf/.local/share/log-hoarder/archived/1/2/0",
    "/Users/stumpf/.local/share/log-hoarder/archived/3/0/0",
    "/Users/stumpf/.local/share/log-hoarder/archived/3/1/0",
    "/Users/stumpf/.local/share/log-hoarder/archived/9/0/0",
]

# Real file sizes observed in the archive
REAL_FILE_SIZES = {
    "small": 3357,       # 1/0/0/224051.log
    "medium": 122063,    # 0/0/0/192442.log
    "large": 1309342,    # 2/1/0/022658.log
    "xlarge": 8810955,   # 3/0/0/235717.log — ollama benchmarking session
}


class TestSpanWithRealSessionPaths:
    """Spans created from actual log-hoarder archived session paths."""

    def test_span_from_real_pane_directory(self) -> None:
        """Given a real archived pane path, When creating a Span, Then it succeeds."""
        span = Span(
            session_path=REAL_PATHS[0],
            span_id=0,
            byte_start=0,
            byte_end=REAL_FILE_SIZES["medium"],
        )

        assert span.session_path == REAL_PATHS[0]
        assert span.length == 122063

    def test_multiple_spans_across_large_session(self) -> None:
        """Given the largest real log (~8.8MB), When segmented into spans, Then spans tile the file."""
        file_size = REAL_FILE_SIZES["xlarge"]
        # Simulate 4 spans detected by context switches (cd, tool change, idle gap)
        boundaries = [0, 500_000, 2_000_000, 6_000_000, file_size]
        spans = [
            Span(
                session_path=REAL_PATHS[3],  # session 3/0/0
                span_id=i,
                byte_start=boundaries[i],
                byte_end=boundaries[i + 1],
                working_dir="/Users/stumpf" if i == 0 else None,
            )
            for i in range(len(boundaries) - 1)
        ]

        assert len(spans) == 4
        assert spans[0].working_dir == "/Users/stumpf"
        assert spans[0].length == 500_000
        assert spans[-1].byte_end == file_size
        # Spans tile the file with no gaps
        for i in range(len(spans) - 1):
            assert spans[i].byte_end == spans[i + 1].byte_start

    def test_span_from_multi_window_session(self) -> None:
        """Given pane paths from different windows in one session, When creating Spans, Then paths differ."""
        span_win0 = Span(
            session_path=REAL_PATHS[3],  # session 3, window 0
            span_id=0,
            byte_start=0,
            byte_end=1000,
        )
        span_win1 = Span(
            session_path=REAL_PATHS[4],  # session 3, window 1
            span_id=0,
            byte_start=0,
            byte_end=1000,
        )

        assert span_win0.session_path != span_win1.session_path


class TestChunkWithRealLogContent:
    """Chunks created from content patterns found in real log-hoarder output."""

    # Real prompt line format: "HH:MM:SS user@host:dir % command"
    REAL_PROMPT_TEXT = (
        "23:57:18 stumpf@macbookpro:~ % ollama pull gemma4:31b-instruct-q8_0\n"
        "pulling manifest\n"
        "Error: pull model manifest: file does not exist\n"
        "23:57:24 stumpf@macbookpro:~ % ollama pull gemma4:26b-instruct-q8_0\n"
        "pulling manifest\n"
        "Error: pull model manifest: file does not exist\n"
    )

    REAL_NAVIGATION_TEXT = (
        "22:40:52 stumpf@macbookpro:~ % cd Dropbox/\n"
        "22:41:35 stumpf@macbookpro:~ % cd Google Drive/My Drive/Author/Shadow\n"
        "22:42:05 stumpf@macbookpro:Author/Shadow % ls\n"
        "Act II - Yandyrs Ledger.md\tShadow's Five Words.gdoc\n"
        "Shadow - Blood Hunter.gdoc\n"
    )

    def test_chunk_from_real_command_output(self) -> None:
        """Given real terminal output with prompts and errors, When creating a Chunk, Then it succeeds."""
        chunk = Chunk(
            session_path=REAL_PATHS[3],
            span_id=0,
            chunk_index=0,
            byte_start=0,
            byte_end=len(self.REAL_PROMPT_TEXT.encode()),
            text=self.REAL_PROMPT_TEXT,
        )

        assert "ollama" in chunk.text
        assert chunk.chunk_index == 0

    def test_chunk_from_real_navigation_session(self) -> None:
        """Given real cd/ls navigation output, When creating a Chunk, Then it preserves content."""
        chunk = Chunk(
            session_path=REAL_PATHS[0],
            span_id=0,
            chunk_index=0,
            byte_start=0,
            byte_end=len(self.REAL_NAVIGATION_TEXT.encode()),
            text=self.REAL_NAVIGATION_TEXT,
        )

        assert "cd Dropbox" in chunk.text
        assert "Author/Shadow" in chunk.text

    def test_chunk_index_key_matches_real_path_format(self) -> None:
        """Given a real session path, When accessing index_key, Then format is path:span:chunk."""
        chunk = Chunk(
            session_path=REAL_PATHS[5],  # session 9/0/0
            span_id=2,
            chunk_index=7,
            byte_start=5000,
            byte_end=6000,
            text="some indexed text",
        )

        expected = "/Users/stumpf/.local/share/log-hoarder/archived/9/0/0:2:7"
        assert chunk.index_key == expected


class TestChunkFromSpanWithRealData:
    """Chunk.from_span with realistic span/chunk tiling of a real log file."""

    def test_tile_small_file_into_single_chunk(self) -> None:
        """Given the smallest real log (3.3KB), When chunked, Then a single chunk covers it."""
        file_size = REAL_FILE_SIZES["small"]
        span = Span(
            session_path=REAL_PATHS[1],
            span_id=0,
            byte_start=0,
            byte_end=file_size,
        )

        chunk = Chunk.from_span(
            span=span,
            chunk_index=0,
            byte_start=0,
            byte_end=file_size,
            text="entire small log content here",
        )

        assert chunk.length == file_size
        assert chunk.span_id == 0

    def test_tile_large_span_into_overlapping_chunks(self) -> None:
        """Given a ~1MB span, When chunked at 4KB with 10% overlap, Then chunks tile correctly."""
        span = Span(
            session_path=REAL_PATHS[2],
            span_id=0,
            byte_start=0,
            byte_end=REAL_FILE_SIZES["large"],
        )

        chunk_size = 4096
        overlap = 410  # ~10% of chunk_size
        stride = chunk_size - overlap
        chunks: list[Chunk] = []
        offset = 0
        idx = 0

        while offset < span.byte_end:
            end = min(offset + chunk_size, span.byte_end)
            chunks.append(
                Chunk.from_span(
                    span=span,
                    chunk_index=idx,
                    byte_start=offset,
                    byte_end=end,
                    text=f"chunk {idx} content",
                )
            )
            offset += stride
            idx += 1

        # First chunk starts at 0
        assert chunks[0].byte_start == 0
        # Last chunk ends at file boundary
        assert chunks[-1].byte_end == REAL_FILE_SIZES["large"]
        # Consecutive chunks overlap
        assert chunks[1].byte_start < chunks[0].byte_end
        # Reasonable number of chunks for ~1.3MB at 4KB stride
        assert len(chunks) > 300

    def test_chunks_do_not_cross_span_boundaries(self) -> None:
        """Given two adjacent spans, When chunking, Then no chunk spans both."""
        boundary = 500_000
        file_size = REAL_FILE_SIZES["large"]

        span_a = Span(
            session_path=REAL_PATHS[2],
            span_id=0,
            byte_start=0,
            byte_end=boundary,
        )
        span_b = Span(
            session_path=REAL_PATHS[2],
            span_id=1,
            byte_start=boundary,
            byte_end=file_size,
        )

        # Last chunk of span_a must end at boundary
        last_a = Chunk.from_span(
            span=span_a,
            chunk_index=99,
            byte_start=boundary - 2000,
            byte_end=boundary,
            text="end of span a",
        )
        # First chunk of span_b must start at boundary
        first_b = Chunk.from_span(
            span=span_b,
            chunk_index=0,
            byte_start=boundary,
            byte_end=boundary + 4096,
            text="start of span b",
        )

        assert last_a.byte_end == first_b.byte_start

        # Crossing the boundary must fail
        with pytest.raises(ValueError, match="span"):
            Chunk.from_span(
                span=span_a,
                chunk_index=100,
                byte_start=boundary - 1000,
                byte_end=boundary + 1000,
                text="crosses boundary",
            )
