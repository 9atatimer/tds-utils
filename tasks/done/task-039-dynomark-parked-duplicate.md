---
id: task-039
kind: bug
title: "dynomark: a parked duplicate counts as filed and parks later re-saves"
created: 2026-10-05
issue: 414
implements: docs/design/DYNOMARK.DESIGN.md
---

The park batch's APPLIED receipt makes the job FILED (`app/run.py:212-213`), and `is_duplicate` (`domain/job.py:170-181`) counts the Graveyard copy, so a re-save after deleting the original is parked.

Evidence, impact and done-criteria: issue #414. Daemon paths are under
`dynomark/daemon/src/dynomark_daemon/`. RED test first (law 5).
