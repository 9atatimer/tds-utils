# TODO_PLAN.md

This file tracks the status of development tasks, lessons learned, and completed work for the `tds-utils` repository.

## How to use this file
1. **Open Tasks**: Add new tasks here. Use checkboxes `[ ]` for pending and `[x]` for completed tasks.
2. **Lessons Learned**: After finishing a task or encountering a significant issue, document the insight here.
3. **Completed Tasks**: Move finished tasks from the "Open Tasks" section to this section.

---

## Open Tasks

- [ ] Task 2: Validate `txtai` integration with real log data.
- [ ] Task 2: Integrate `indexer.py` into `tmux_shepherd.sh` cron mode.
- [ ] Task 2: Phase 2 - Implement `SqliteVecAdapter` for a lighter-weight alternative.
- [ ] Task 3: Add `log_search` alias or bin link for easier CLI access.

---

## Lessons Learned

- **Securing Log Permissions**: Use `umask 077` at the start of logging and management scripts to ensure new directories and files are restricted to the owner. Perform a recursive `chmod -R 700` on the log directory in management scripts like `tmux_shepherd.sh` to fix existing permissions.
- **Hexagonal Architecture**: Decoupling the search index interface (`SearchIndexPort`) from the implementation (`TxtaiAdapter`) allows for an easy swap from a "heavy" framework like `txtai` to a lighter one like `sqlite-vec` later, while keeping the core logic intact.
- **Single Source of Truth**: Storing only metadata and embeddings in the vector index while pointing to the original log files minimizes data duplication and maintains the integrity of the primary log store.

---

## Completed Tasks

- [x] Task 1: Secure log permissions in `log-hoarder` (restrict to owner read/write).
- [x] Task 1.1: Fix `tmux.conf` durable double/triple click selection in `root` table.
- [x] Task 2 (Design): Create `SEMANTIC-SEARCH.DESIGN.md` and scaffold Hexagonal architecture with `txtai` MVP.
- [x] Task 2 (Scaffolding): Implement domain models, ports, `TxtaiAdapter`, indexer, and searcher.
