---
id: task-038
kind: bug
title: "dynomark: the omnibox never shows tier-2 hits when tier 1 returns seven rows"
created: 2026-10-05
issue: 413
implements: docs/design/DYNOMARK.DESIGN.md
---

`extension/src/app/omnibox.ts:24, 71, 84`: tier 1 is asked for 7 and the merged list is sliced to 7, so appended tier-2 hits are cut off. Goal 4.

Evidence, impact and done-criteria: issue #413. Daemon paths are under
`dynomark/daemon/src/dynomark_daemon/`. RED test first (law 5).
