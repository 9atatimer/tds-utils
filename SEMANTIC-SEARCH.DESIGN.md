# SEMANTIC-SEARCH.DESIGN.md

## Overview

The goal is to enable semantic search over terminal session logs stored by `log-hoarder`. This allows a user to query their terminal history using natural language (e.g., "how did I fix that docker permission error?") and find the relevant session log.

## Core Principle: Full Coverage, No Duplication

A single terminal session may span multiple projects, repos, and tasks. Sampling or truncating log content is not acceptable -- **every byte of every log file must be covered by the semantic index**.

However, the index must not become a second copy of the logs. The index stores only:

*   **Embeddings** (vector representations of text chunks)
*   **Metadata** (source file path, byte offset, chunk boundaries, timestamp)

The original log files remain the **single source of truth** for content. Search results point back to the source file and location -- the user reads the log, not the index.

## Indexing Strategy: Chunked Full-File Embedding

Each log file is read in its entirety and split into fixed-size overlapping text chunks:

*   **Chunk size**: ~512-1024 tokens (tuned to embedding model context window)
*   **Overlap**: ~10-20% between adjacent chunks to avoid splitting thoughts at boundaries
*   **Per chunk**: generate one embedding vector, store it with metadata (source path, byte offset, chunk index)
*   **Non-printable filtering**: strip control characters before embedding, but preserve byte offsets into the original file so results map back accurately

At search time, matching chunks return the source file path and byte offset, allowing the user to jump directly to the relevant section of the log.

## Architecture: Hexagonal (Ports & Adapters)

To allow swapping the storage backend (e.g., from `sqlite-vec` to `txtai`) without touching business logic, we will separate the system into three layers.

### 1. Domain Layer (Core Logic)
*   **Entities**: `LogEntry` (metadata, path, slug), `LogChunk` (source path, byte offset, chunk index, text for embedding).
*   **Ports (Interfaces)**:
    *   `SearchIndexPort`: Abstract methods for `add_chunks(chunks, vectors)` and `search(query_vector, limit)`.
    *   `EmbeddingPort`: Abstract method for `get_embedding(text)`.

### 2. Infrastructure Layer (Adapters)
*   **Adapters (Current - Phase 1 MVP)**:
    *   `TxtaiAdapter`: A single adapter that implements both ports using the `txtai` framework (turnkey embeddings + metadata storage).
*   **Adapters (Future - Phase 2)**:
    *   `SqliteVecAdapter`: Implements `SearchIndexPort` using `sqlite3` and the `sqlite-vec` extension for a lighter-weight alternative.
    *   `OllamaAdapter`: Implements `EmbeddingPort` by calling the local Ollama API.

### 3. Application Layer (CLI Entry Points)
*   **`log_indexer.py`**: Coordinates the flow: Read Full Log → Chunk → Get Embeddings (via Port) → Store Chunks (via Port).
*   **`log_search.py`**: Coordinates the flow: User Query → Get Embedding (via Port) → Retrieve Matching Chunks (via Port) → Return source file path + byte offset.

---

## Directory Structure (Proposed)

```
log-hoarder/
├── search/
│   ├── domain/
│   │   ├── models.py      # Data classes
│   │   └── ports.py       # Abstract base classes
│   ├── adapters/
│   │   ├── sqlite_vec.py  # SQLite-vec implementation
│   │   └── ollama.py      # Ollama implementation
│   ├── app.py             # Glue/Dependency Injection
│   ├── indexer.py         # CLI Indexer
│   └── searcher.py        # CLI Searcher
└── requirements.txt
```

---

## Technical Strategy: SQLite-vec

Since `sqlite-vec` is a loadable extension, we will:
1.  Check for its presence in the user's environment.
2.  Default to a standard SQLite implementation for metadata, using the extension specifically for the `vec_f32` virtual tables.
3.  If `txtai` is chosen later, `app.py` will simply instantiate the `TxtaiAdapter` instead of the SQLite/Ollama pair.

## What the Index Must NOT Contain

The index is a lookup structure, not a data store:

*   **No raw log text** -- the index stores embeddings and metadata only
*   **No truncated samples** -- partial content defeats the purpose of semantic search
*   The index should be rebuildable from the log files at any time

## Integration with `log-hoarder`

*   **`tmux_shepherd.sh`**: Add a call to `log_indexer.py` in the `run_cron_mode` flow, after `brand_pane_dir`.
*   **Configuration**: Use existing `LLM_ENDPOINT` and `LLM_MODEL` environment variables, adding new ones if needed (e.g., `EMBEDDING_MODEL="nomic-embed-text"`).

## Future Enhancements

*   **Continuous Indexing**: Use a file watcher (like `fswatch`) to index logs as soon as they are archived.
*   **TUI for Search**: A more interactive terminal UI for browsing and searching logs.
*   **Contextual RAG**: Using the retrieved log as context for a local LLM to answer questions about the session directly.

---

## Design Sign-off Required

Please review this design and provide feedback or approval before implementation begins.
