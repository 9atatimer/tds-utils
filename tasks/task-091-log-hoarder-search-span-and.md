---
id: task-091
kind: task
title: "log-hoarder search: span and chunk pipeline"
created: 2026-11-14
implements: docs/design/SEMANTIC-SEARCH.DESIGN.md
---

`Segmenter` and `Chunker` (pure domain, text in, spans and chunks out), `SearchIndexPort` and `TxtaiAdapter` keyed `session:span:chunk` with byte offsets, an `EmbeddingPort`, the indexer and searcher moved into `search/`, `log_search` wired to the searcher (smoketests S4 and S5 pass), the indexer called from `tmux_shepherd.sh` cron mode.
Purge the sampling code: `content_sample`, `get_log_sample()`, `sample_logs()` becomes `extract_branding_context()`.
Later: `SqliteVecAdapter` plus Ollama adapter; compressed log storage; smoketests for project-scoped, cross-project and compressed-log search.
