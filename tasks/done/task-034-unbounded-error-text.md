---
id: task-034
kind: bug
title: "chores: unbounded backend error text reaches run.json and the never-pruned ledger"
created: 2026-09-28
issue: 297
implements: docs/design/CHORES.DESIGN.md
---

See the issue. RED test first: a large backend `error.message` reaches `run.json` and the ledger capped at the 200 characters its sibling error paths use.
