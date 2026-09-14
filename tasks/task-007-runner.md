---
id: task-007
kind: task
title: chores: run use case
created: 2026-09-14
blocked_by: [task-006]
implements: docs/design/CHORES.DESIGN.md
---

`run_chore(name, deps)` resolves definition and backend, resolves secrets, builds the explicit environment, executes prompt or command, applies spend policy, writes every transition and the ledger row, redacts every byte, posts notifications per `notify_on`, and applies the breaker. Statuses covered by tests: SUCCEEDED, FAILED, TIMED_OUT, BUDGET_EXCEEDED, OFFLINE, KILLED. Subprocess adapter: clean env, cwd, SIGTERM then SIGKILL after 10s grace, stdout/stderr to separate files.
