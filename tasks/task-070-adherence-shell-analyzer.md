---
id: task-070
kind: task
title: "adherence: the shell code model"
created: 2026-10-24
issue: 594
blocked_by: [task-061]
implements: docs/design/ARCHITECTURE.ARCH-ADHERENCE.md
---
A `CodeModelPort` adapter for shell over ast-grep's Bash grammar: regions
by the `# --- Section ---` markers, bodies, dependencies (commands a
script requires); Anatomy, Stub, Complexity where lizard covers it, and
Dependency apply, and every other check reports not applicable to the
language rather than coverage missing. RED first over a fixture shaped
like `bin/tds-release`, then `bin/adhere measure` over `bin/` itself.
