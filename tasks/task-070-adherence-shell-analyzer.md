---
id: task-070
kind: task
title: "adherence: the shell code model"
created: 2026-10-24
issue: 594
blocked_by: [task-069]
implements: docs/design/ARCHITECTURE.ARCH-ADHERENCE.md
---
A `CodeModelPort` adapter for shell over the shared `astgrep` adapter's
Bash grammar (task-069 lands it): regions by the `# --- Section ---`
markers, bodies, dependencies (commands a script requires). Anatomy,
Stub and Dependency apply; Complexity applies only where lizard covers
the language; every other check reports coverage missing for the unit,
with the reason that the check does not read shell, as G11 and the
architecture's coverage rule say. RED first over a fixture shaped like
`bin/tds-release`, then `bin/adhere measure` over `bin/` itself.
