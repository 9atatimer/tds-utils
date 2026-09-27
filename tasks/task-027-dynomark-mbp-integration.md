---
id: task-027
kind: task
title: "dynomark phase 4: mbp integration -- real profile, host manifest, launchd daemon, live round trip, Goal 2 measured"
created: 2026-09-27
blocked_by: [task-025, task-026]
implements: docs/design/DYNOMARK.DESIGN.md
---

The one phase that needs the laptop. Nothing here is unit-tested; it is
the PoC acceptance run, recorded in the learning checkpoint with numbers.

1. Install the daemon under launchd for the user (owner-only socket, store
   under the state directory); `dynomark-daemon --check` green with Ollama
   reachable.
2. Load the unpacked extension into the real Chrome profile; register the
   native-messaging host manifest with the real extension id; hello/version
   exchange succeeds.
3. Backfill nothing (Open Question 3 in the design); start with an empty
   corpus.
4. Save ten pages into `Follow Up` with Ctrl+D, including two logged-in
   pages. Assert: each is filed under `Dynomark` within Goal 2's bound
   (measure ingest-received -> `APPLIED`), captured text is searchable via
   `bm`, logged-in pages captured from the tab.
5. Undo one batch; make an unrelated edit first and assert it survives.
6. Kill Chrome mid-batch (or reload the extension) and assert resume from
   the cursor with no duplicate folder.
7. Save one page from the phone; assert the writer files it (fetch
   capture; logged-in loss accepted per Key Decisions).
8. Run a week of daily use on the writer host; record every manual repair.

Acceptance: the eight steps above recorded with numbers in the checkpoint;
any design divergence cut as an issue per the retrospective skill, never
edited into the frozen design.
