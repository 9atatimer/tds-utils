---
id: task-008
kind: task
title: chores: tick use case
created: 2026-09-14
blocked_by: [task-007]
implements: docs/design/CHORES.DESIGN.md
---

`tick(deps)`: lock, write `last_tick`, load definitions (INVALID records for failures), due/missed detection per chore, admission with every SKIP/DEFERRED reason recorded, INTERRUPTED detection for RUNNING records whose pid is gone, detached spawn of `chores run <name>` for admitted chores, `catch_up` semantics. Fake clock drives every scenario; no sleeps.
