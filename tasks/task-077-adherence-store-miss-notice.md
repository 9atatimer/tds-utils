---
id: task-077
kind: bug
title: "adherence: a store miss or identity mismatch re-measures silently"
created: 2026-11-06
issue: 686
blocked_by: []
implements: docs/design/ARCHITECTURE.ARCH-ADHERENCE.md
---
On a base-report store miss or identity mismatch the judge re-measures
the base with no notice (`application/judge.py:130-134`), against A:478.
Done when tests show each cause produces a notice naming it and the verdict
is otherwise unchanged.
