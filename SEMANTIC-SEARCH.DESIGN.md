# SEMANTIC-SEARCH.DESIGN.md

## Overview

The goal is to enable semantic search over terminal session logs stored by `log-hoarder`. This allows a user to query their terminal history using natural language (e.g., "how did I fix that docker permission error?") and find the relevant session log.

## Architecture: Hexagonal (Ports & Adapters)

To allow swapping the storage backend (e.g., from `sqlite-vec` to `txtai`) without touching business logic, we will separate the system into three layers.

### 1. Domain Layer (Core Logic)
*   **Entities**: `LogEntry` (metadata, path, slug) and `Vector` (the embedding).
*   **Ports (Interfaces)**:
    *   `SearchIndexPort`: Abstract methods for `add_entry(entry, vector)` and `search(query_vector, limit)`.
    *   `EmbeddingPort`: Abstract method for `get_embedding(text)`.

### 2. Infrastructure Layer (Adapters)
*   **Adapters (Current - Phase 1)**:
    *   `SqliteVecAdapter`: Implements `SearchIndexPort` using `sqlite3` and the `sqlite-vec` extension.
    *   `OllamaAdapter`: Implements `EmbeddingPort` by calling the local Ollama API.
*   **Adapters (Future - Phase 2)**:
    *   `TxtaiAdapter`: A single adapter that could implement both ports using the `txtai` framework.

### 3. Application Layer (CLI Entry Points)
*   **`log_indexer.py`**: Coordinates the flow: Read Log → Get Embedding (via Port) → Store (via Port).
*   **`log_search.py`**: Coordinates the flow: User Query → Get Embedding (via Port) → Retrieve Matches (via Port).

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
