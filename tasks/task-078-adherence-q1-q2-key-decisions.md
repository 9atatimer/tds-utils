---
id: task-078
kind: bug
title: "adherence: the architecture still lists Q1 and Q2 as open"
created: 2026-11-06
issue: 689
blocked_by: []
implements: docs/design/ARCHITECTURE.ARCH-ADHERENCE.md
---
task-069 resolved the architecture questions Q1 and Q2 but never appended
their Key Decisions rows, and A:533-540 still lists both open. Q1: Trace
matches name plus parameter names, ignoring the keyword-only shape; in JS,
ports-as-keywords is the options object. Q2: the type name is read from
syntax, with no compiler sidecar. Done when the Key Decisions table carries
both rows and A:533-540 marks them resolved.
