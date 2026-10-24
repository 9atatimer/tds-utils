---
id: task-058
kind: task
title: "adherence: measure, the Report, and the Hexagonal checks"
created: 2026-10-24
issue: 592
blocked_by: [task-057]
implements: docs/design/ARCHITECTURE.ARCH-ADHERENCE.md
---
`measure` by the architecture's signature, with `Report`, `Score`,
`Coverage` and `Finding` (identity, evidence bound), and the first
quality's rule checks over the `CodeModel`, each RED first against
`measure` with fakes behind every port:

- A repository is measured
- A domain leak is found
- An inward arrow holds
- A cycle is found
- A port without a fake is found
- A named seam is missing (needs `RecordsPort`'s fake only; the markdown
  adapter is task-059)
- An uncovered language is reported
- A report quotes no more than the evidence
- Repository code is never run (the adapter contract: bytes in, no
  import, no build; the subprocess allowlist)

Done when `bin/adhere measure` over the task-057 fixture prints the
Hexagonal score and its findings as JSON, and every other quality reads
as coverage missing with a reason.
