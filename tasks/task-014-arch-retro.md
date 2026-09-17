---
id: task-014
kind: task
title: "chores: as-built entry at release, then the status transition"
created: 2026-09-14
blocked_by: [task-015, task-016, task-017, task-018, task-019]
implements: docs/design/CHORES.DESIGN.md
---

Phase 8 ran on 2026-09-14/17 (drift issues #283-#287 cut, Key Decisions
appended, lessons routed). What remains is release-bound: when
`bin/tds-release` puts the chores commit live, write the first
`docs/arch/` entry in tds-utils (index + `chores/ARCHITECTURE.md` + html
glance) describing what is deployed, including the built-but-not-designed
facts from #286; then Todd moves CHORES.DESIGN.md from APPROVED to
IMPLEMENTED once the drift tasks above are closed. Not before: the
as-built holds deployed facts only.
