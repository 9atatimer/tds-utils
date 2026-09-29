---
id: task-033
kind: bug
title: "chores: a KILLED run breaks the breaker's failure streak, so a chore that always hangs never pauses"
created: 2026-09-28
issue: 296
implements: docs/design/CHORES.DESIGN.md
---

See the issue. RED tests first: KILLED is transparent to the streak the way OFFLINE is (neither a failure nor a reset), and `threshold=0` cannot return PAUSE.
