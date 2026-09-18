---
id: task-004
kind: task
title: chores: run record FSM, ledger row, ceiling, breaker, admission, redaction
created: 2026-09-14
blocked_by: [task-003]
implements: docs/design/CHORES.DESIGN.md
---

Domain `RunRecord` with the Run state machine (illegal transitions raise), `LedgerRow` flattening, `ceiling_policy(rows_24h, backend_ceiling, global_ceiling, declared_budget)`, `circuit_breaker(recent_statuses, threshold)`, `admission_policy(flags)` with every SKIP reason, and `redact(text, secrets)`. Architect tests: grep the domain for vendor names, paths, env vars, model ids.
