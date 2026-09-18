---
id: task-002
kind: task
title: chores: cron Schedule value and due policy
created: 2026-09-14
blocked_by: [task-001]
implements: docs/design/CHORES.DESIGN.md
---

Domain `Schedule` parses 5-field cron (numbers, `*`, ranges, steps, lists, names for months/days) and answers `next_after(dt)` / `matches(dt)`; `due_policy(schedule, last_fired, now, grace)` returns FIRE, MISSED(n) or NOT_DUE. Hypothesis property: `next_after` is monotone and always matches. Design: Subsystem 2, Key Decisions (cron evaluation).
