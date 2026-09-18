---
id: task-017
kind: bug
title: "chores: status drift (state dir size, per-chore ceilings and remaining, ledger-shrink warning, 500ms goal)"
created: 2026-09-17
issue: 285
implements: docs/design/CHORES.DESIGN.md
---

See the issue. StatusView gains state_dir_bytes, a per-chore scope with remaining, the ledger-shrink warning; a perf test pins the 500ms goal at 1000 records.
