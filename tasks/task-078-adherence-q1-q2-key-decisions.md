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
matches the function name, the parameter names in order, and which are
keyword-only; in TS and JS a destructured object's members and the
`Vocabulary.options_objects` parameters are keyword-only (Issue#590,
comment of 2026-10-25). Q2: the declared type as written is enough, read
from syntax with no compiler sidecar. Done when the Key Decisions table carries
both rows and A:533-540 marks them resolved.
