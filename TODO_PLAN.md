# TODO_PLAN.md

This file tracks the status of development tasks, lessons learned, and completed work for the `tds-utils` repository.

## How to use this file
1. **Open Tasks**: Add new tasks here. Use checkboxes `[ ]` for pending and `[x]` for completed tasks.
2. **Lessons Learned**: After finishing a task or encountering a significant issue, document the insight here.
3. **Completed Tasks**: Move finished tasks from the "Open Tasks" section to this section.

---

## Open Tasks

- [x] Task 2a: Implement `Span` and `Chunk` domain models in `search/domain/models.py`.
- [ ] Task 2b: Implement `Segmenter` — reads a log file, detects span boundaries (cd commands, tool switches, idle gaps), returns `Span` objects with byte offsets. Pure domain logic in `search/domain/segmenter.py`.
- [ ] Task 2c: Implement `Chunker` — splits a span's text into embedding-sized `Chunk` objects with overlap. Pure domain logic in `search/domain/chunker.py`.
- [ ] Task 2d: Update `SearchIndexPort` and `TxtaiAdapter` — store chunk embeddings keyed by `session:span:chunk` with byte-offset metadata. Add `EmbeddingPort` to `ports.py`.
- [ ] Task 2e: Update indexer — replace `get_log_sample` with full pipeline: read log → segment into spans → chunk each span → embed → store. Move `indexer.py` into `search/`.
- [ ] Task 2f: Update searcher — query returns chunk hits, group by span, return ranked span references. Move `searcher.py` into `search/`.
- [ ] Task 3: Validate span-based indexing and search with real log data.
- [ ] Task 4: Integrate indexer into `tmux_shepherd.sh` cron mode.
- [ ] Task 5: Phase 2 — Implement `SqliteVecAdapter` + `OllamaAdapter` for lighter-weight alternative.
- [ ] Task 6: Add `log_search` alias or bin link for easier CLI access.

---

## Lessons Learned

- **Securing Log Permissions**: Use `umask 077` at the start of logging and management scripts to ensure new directories and files are restricted to the owner. Perform a recursive `chmod -R u+rwX,go-rwx` on the log directory in management scripts like `tmux_shepherd.sh` to fix existing permissions without making non-executable files executable.
- **Hexagonal Architecture**: Decoupling the search index interface (`SearchIndexPort`) from the implementation (`TxtaiAdapter`) allows for an easy swap from a "heavy" framework like `txtai` to a lighter one like `sqlite-vec` later, while keeping the core logic intact.
- **Single Source of Truth (target state)**: The index will store only embeddings and metadata (session path, span ID, chunk index, byte offsets). The original log files are the sole content store. No raw text in the index, no sampling or truncation -- every byte of every log must be covered by embeddings. Note: the current MVP scaffolding still uses content sampling; Task 2a-2f replaces this with span-based chunked indexing.
- **Full Coverage Required**: A single session may span multiple projects and tasks. Sampling head/tail lines is useless for semantic search -- the indexer must segment into spans and chunk the entire file.
- **Spans vs Chunks**: Chunks are the unit of embedding (sized for the model's context window). Spans are the unit of retrieval (logically coherent stretches of activity). Search returns span references; chunks are an implementation detail of the index.

---

## Completed Tasks

- [x] Task 1: Secure log permissions in `log-hoarder` (restrict to owner read/write).
- [x] Task 1.1: Fix `tmux.conf` durable double/triple click selection in `root` table.
- [x] Task 2 (Design): Create `SEMANTIC-SEARCH.DESIGN.md` and scaffold Hexagonal architecture with `txtai` MVP.
- [x] Task 2 (Scaffolding): Implement domain models, ports, `TxtaiAdapter`, indexer, and searcher.
- [x] Task 2 (Design revision): Refine design with span/chunk model — spans as semantic segments, chunks as embedding units, search groups by span.
