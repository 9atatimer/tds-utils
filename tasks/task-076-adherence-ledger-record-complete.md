---
id: task-076
kind: bug
title: "adherence: the ledger record drops abstentions, passes and confidence"
created: 2026-11-06
issue: 685
blocked_by: []
implements: docs/design/ARCHITECTURE.ARCH-ADHERENCE.md
---
The record both stores write keeps findings only, with one run-wide `ran`
list (`adapters/file_store.py:100-158`, `adapters/warehouse.py:106`),
against A:415-419. Done when contract tests for both stores show a record
round-trips abstentions, passes, each finding confidence and a per-check
`ran`.
