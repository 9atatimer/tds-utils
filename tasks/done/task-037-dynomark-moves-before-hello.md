---
id: task-037
kind: bug
title: "dynomark: user moves observed before a full hello are dropped"
created: 2026-10-05
issue: 412
implements: docs/design/DYNOMARK.DESIGN.md
---

`extension/src/app/treeWatch.ts:168` returns before reporting or recording a move when the session is not full; the daemon never reconciles it from `tree.snapshot`. The feedback is lost.

Evidence, impact and done-criteria: issue #412. Daemon paths are under
`dynomark/daemon/src/dynomark_daemon/`. RED test first (law 5).
