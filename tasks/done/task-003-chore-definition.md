---
id: task-003
kind: task
title: chores: Chore definition, Budget, Usage, spend policy
created: 2026-09-14
blocked_by: [task-001]
implements: docs/design/CHORES.DESIGN.md
---

Domain `Chore` built from a parsed front-matter mapping enforces the invariants in Data Model (unique name charset, kind/backend/command consistency, non-negative budgets, unknown keys rejected). `Budget`, `Usage`, `spend_policy(usage, budget)` -> CONTINUE / STOP(reason). The YAML parsing itself is an adapter (task-005); this task takes a plain mapping.
