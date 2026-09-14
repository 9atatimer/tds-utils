---
id: task-011
kind: task
title: chores: Textual TUI
created: 2026-09-14
blocked_by: [task-009]
implements: docs/design/CHORES.DESIGN.md
---

`chores ui`: a Textual app rendering `StatusView` (chore table, totals, notifications, scheduler staleness) refreshed every 5s, with run-now, pause/resume, open-run and dismiss actions calling the same application functions as the CLI. Tests use Textual's pilot against fakes.
