---
id: task-035
kind: bug
title: "chores: tick can close a run that actually finished, discarding its usage and booking a false breaker failure"
created: 2026-09-28
issue: 298
implements: docs/design/CHORES.DESIGN.md
---

See the issue. Needs a design call first (tick re-checks liveness after winning the CAS, or the runner amends a lost race). RED test: a store double lets the tick win, and the run still keeps its usage, its ledger row and its true status, with no breaker failure booked.
