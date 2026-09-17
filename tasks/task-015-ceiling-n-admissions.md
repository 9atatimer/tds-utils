---
id: task-015
kind: bug
title: chores: a ceiling can be exceeded by N admissions in one tick
created: 2026-09-17
issue: 283
implements: docs/design/CHORES.DESIGN.md
---

See the issue. Admitted-but-unfinished runs must count their declared budget as spent until their ledger row lands; tick must carry the budgets it admitted in the same pass.
