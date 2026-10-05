---
id: task-040
kind: bug
title: "dynomark: undo keeps an owned root the batch created and does not report it"
created: 2026-10-05
issue: 415
implements: docs/design/DYNOMARK.DESIGN.md
---

`domain/batch.py:554-570, 684-686`: the root-creating op's revert is omitted with no UndoDrop, so Goal 6's report is silent about it.

Evidence, impact and done-criteria: issue #415. Daemon paths are under
`dynomark/daemon/src/dynomark_daemon/`. RED test first (law 5).
