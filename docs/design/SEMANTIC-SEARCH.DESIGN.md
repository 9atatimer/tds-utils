# SEMANTIC-SEARCH.DESIGN.md

## Overview

The goal is to enable semantic search over terminal session logs stored by `log-hoarder`. This allows a user to query their terminal history using natural language (e.g., "how did I fix that docker permission error?") and find the relevant session log.

## Terminology

*   **Session**: A single tmux pane's log directory (`archived/SESSION/WINDOW/PANE/`), containing one or more `.log` files.
*   **Span**: A logically coherent stretch of activity within a session -- typically bounded by context shifts such as `cd` commands that change the working directory, switching to a different tool or language, or other significant changes in what the user is doing. A span is the primary unit returned by search.
*   **Chunk**: A fixed-size piece of text within a span, sized for the embedding model's context window. Chunks are the unit of embedding; spans are the unit of retrieval.

## Core Principle: Full Coverage, No Duplication

A single terminal session may span multiple projects, repos, and tasks. Sampling or truncating log content is not acceptable -- **every byte of every log file must be covered by the semantic index**.

However, the index must not become a second copy of the logs. The index stores only:

*   **Embeddings** (vector representations of text chunks)
*   **Metadata** (session path, span ID, chunk index, byte offsets)

The original log files remain the **single source of truth** for content. Search results point back to the source file and byte range -- the user reads the log, not the index.

## Segmentation: Sessions → Spans → Chunks

### Span Detection (Segmenter)

The segmenter reads a complete log file and identifies span boundaries. A new span starts when the session's context shifts significantly:

*   **`cd` commands** that change the working directory
*   **Tool/environment switches** (e.g., entering a REPL, SSH-ing to another host, launching a database client)
*   **Long idle gaps** suggesting the user returned to a different task
*   **Explicit markers** if we add them later (e.g., a shell hook that emits a separator)

The segmenter is pure domain logic -- it takes text in and returns a list of span boundaries (byte offsets). It has no dependency on the index or embedding engine.

Each span carries metadata:

*   `session_path`: the pane directory
*   `span_id`: ordinal within the session (0, 1, 2, ...)
*   `byte_start`, `byte_end`: offsets into the source log file
*   `working_dir`: the working directory at span start (if detectable)

### Chunking (within Spans)

Each span is split into fixed-size chunks for embedding:

*   **Chunk size**: ~512-1024 tokens (tuned to embedding model context window)
*   **Overlap**: ~10-20% between adjacent chunks to avoid splitting thoughts at boundaries
*   **Boundary alignment**: chunks do not cross span boundaries -- a new span always starts a new chunk
*   **Non-printable filtering**: strip control characters before embedding, but preserve byte offsets into the original file so results map back accurately

Each chunk carries metadata:

*   `session_path`, `span_id`: inherited from the parent span
*   `chunk_index`: ordinal within the span (0, 1, 2, ...)
*   `byte_start`, `byte_end`: offsets into the source log file

### Index Reference Format

Every embedding in the index is keyed by `session:span:chunk` and carries enough metadata to locate the original bytes. Search queries return chunk hits; the application layer groups those hits by span and returns span references ranked by best chunk score.

## Architecture: Hexagonal (Ports & Adapters)

To allow swapping the storage backend without touching business logic, we separate the system into three layers.

### 1. Domain Layer (Core Logic)

*   **Entities**:
    *   `LogEntry` — session-level metadata (path, timestamp, slug)
    *   `Span` — a logically coherent segment (session path, span ID, byte range, working dir)
    *   `Chunk` — an embedding-sized piece of a span (session path, span ID, chunk index, byte range, text for embedding)
*   **Domain Services**:
    *   `Segmenter` — reads a log file, returns a list of `Span` objects with byte offsets
    *   `Chunker` — splits a `Span`'s text into `Chunk` objects
*   **Ports (Interfaces)**:
    *   `SearchIndexPort` — abstract methods for storing chunks with embeddings and querying them
    *   `EmbeddingPort` — abstract method for generating an embedding vector from text

### 2. Infrastructure Layer (Adapters)

*   **Phase 1 (MVP)**:
    *   `TxtaiAdapter` — implements both `SearchIndexPort` and `EmbeddingPort` using the `txtai` framework (turnkey embeddings + SQLite metadata storage)
*   **Phase 2**:
    *   `SqliteVecAdapter` — implements `SearchIndexPort` using `sqlite3` + `sqlite-vec` extension
    *   `OllamaAdapter` — implements `EmbeddingPort` by calling the local Ollama API

### 3. Application Layer (Orchestration + CLI)

*   **Indexer flow**: Discover unindexed sessions → Read log → Segment into spans → Chunk each span → Embed chunks (via `EmbeddingPort`) → Store in index (via `SearchIndexPort`)
*   **Search flow**: User query → Embed query → Retrieve matching chunks → Group by span → Return ranked span references (session path, span ID, byte range, score)

For short spans, the entire span text can be used as RAG context. For long spans, the matching chunk(s) plus surrounding context within the span are returned.

---

## Directory Structure

```
log-hoarder/
├── search/
│   ├── domain/
│   │   ├── models.py       # LogEntry, Span, Chunk dataclasses
│   │   ├── ports.py        # SearchIndexPort, EmbeddingPort ABCs
│   │   ├── segmenter.py    # Log → Spans (pure domain logic)
│   │   └── chunker.py      # Span → Chunks (pure domain logic)
│   ├── adapters/
│   │   └── txtai_adapter.py  # Phase 1 MVP adapter
│   ├── app.py              # Factory / dependency injection
│   ├── indexer.py           # CLI indexer (moved from top-level)
│   └── searcher.py          # CLI searcher (moved from top-level)
└── requirements.txt
```

---

## What the Index Must NOT Contain

The index is a lookup structure, not a data store:

*   **No raw log text** -- the index stores embeddings and metadata only
*   **No truncated samples** -- partial content defeats the purpose of semantic search
*   The index should be rebuildable from the log files at any time

## Integration with `log-hoarder`

*   **`tmux_shepherd.sh`**: Add a call to the indexer in `run_cron_mode`, after `brand_pane_dir`.
*   **Configuration**: Use existing `LLM_ENDPOINT` and `LLM_MODEL` environment variables, adding new ones if needed (e.g., `EMBEDDING_MODEL`).

## Open Issues

### Compressed Log Storage (forward-looking)

Logs can remain uncompressed for the MVP, but the design must not paint us into a
corner — perpetual storage of raw terminal logs will need compression eventually.

Implications to keep in mind during implementation:

*   **Byte offsets in the index should reference uncompressed content.** This keeps the
    index format stable regardless of whether the underlying file is compressed or not.
*   **Log-reading code** (segmenter, chunker, search display) should go through a
    single file-access abstraction so compression support can be added in one place later.
*   **Indexer** will eventually need to handle both `.log` and `.log.zst`/`.log.gz`
    files during any migration period.

Design decisions to resolve before implementing compression:
1. Compression format (gzip for ubiquity vs zstd for seekability and ratio)
2. Per-file or per-session granularity
3. Whether to support random access (e.g., zstd seekable format) or always decompress fully

---

## Future Enhancements

*   **Continuous Indexing**: Use a file watcher (like `fswatch`) to index logs as soon as they are archived.
*   **TUI for Search**: A more interactive terminal UI for browsing and searching logs.
*   **Contextual RAG**: Using the retrieved span as context for a local LLM to answer questions about the session directly.
*   **Span refinement via LLM**: Use a local LLM to improve span boundary detection beyond heuristic rules.
