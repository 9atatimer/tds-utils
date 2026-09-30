---
id: task-023
kind: task
title: "dynomark phase 1: daemon domain and use cases over fakes (ingest through undo)"
created: 2026-09-27
blocked_by: [task-022]
implements: docs/design/DYNOMARK.DESIGN.md
---

The daemon runtime's core, driven by the Behaviors and Interfaces rows,
each RED test calling the row's signature with fakes from task-022. No
adapter, no I/O, no sleep.

Rows, in order; one RED then one GREEN commit each, `(RED)`/`(GREEN)` in
the subject:

1. A save is ingested; idempotent on (`NodeId`, `Identity`).
   `Identity` normalization is daemon-side and is its own pure test.
2. Content falls back to fetch (`capture`, fetch fake); fetch failure
   leaves `source` `none` and the job continues.
3. A job is processed to an entry; a word only in captured text is found
   by `search_corpus` through the store fake.
4. A failed enrichment is retried per `RetryPolicy`, then `FAILED`; no
   `write_batch` references the identity.
5. An entry is placed (neighbours from the store fake, fake completion
   echoing a folder); placement respects a lock; `place` is pure given the
   same completion output (Goal 3).
6. A placement becomes a batch (`file`): operations + inverse, `PROPOSED`,
   the move consumes the `Follow Up` node. An out-of-boundary path raises
   before any batch row exists (Goal 8). `OwnedRoots` is a value input.
7. A duplicate identity is parked: new node -> `Graveyard`, existing
   placement untouched.
8. A receipt is processed: `APPLIED` -> `FILED` + snapshot stored;
   `PARTIAL` -> `FAILED` + `PROPOSED` inverse of the prefix; `REJECTED`
   -> `FAILED`. Receipt delivered twice records once.
9. A reader host never writes: `place`, `file`, `undo` with role `reader`
   return `NotWriter`, no batch row; the job reaches `INDEXED` without
   `place` being called.
10. A batch is undone: guarded inverse; a moved or vanished node and a
    non-empty created folder are dropped and reported.
11. Tier-2 search: fusion in the domain over the store's two candidate
    lists.
12. The local index is built: exact field set, <= 512 bytes per row.
13. Job state machine as a table-driven test: every transition in the
    design's table and no other.
14. Learning checkpoint.

Acceptance: every row above has a kept test whose name cites the
Behaviors row; domain modules import no vendor, no sqlite, no HTTP
(mechanical purity test per the style-python skill); mypy strict and Ruff
clean.
