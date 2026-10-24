---
id: task-058
kind: task
title: "adherence: measure, the Report, and the Hexagonal checks"
created: 2026-10-24
issue: 592
blocked_by: [task-057]
implements: docs/design/ARCHITECTURE.ARCH-ADHERENCE.md
---
`measure` by the architecture's signature, which takes `judge:
DecisionPort`, so this task also defines `DecisionPort`'s protocol, its
`no_judge` adapter (the typed `unavailable` failure) and its fake; the
decide adapter and the questions are task-064. With it: `Report`,
`Score`, `Coverage`, `Finding` (identity, evidence bound), `Notice`, and
the Hexagonal rule checks over the `CodeModel`. RED first, one row per
commit, against `measure` with fakes behind every port:

- A repository is measured
- An undeclared repository is measured
- An unreadable declaration is not run
- The Declared quality cannot be exempted
- A domain leak is found
- An inward arrow holds
- A cycle is found
- A port without a fake is found
- A named seam is missing (against `RecordsPort`'s fake only; the
  markdown adapter is task-059)
- An uncovered language is reported
- A report quotes no more than the evidence
- The same finding everywhere (the pure `Finding.identity` digest; the
  four places that call it are later tasks, and need no new test here)

`cli/main.py` gains the `measure` command and the JSON presenter, enough
for the done check and no more; the other presenters are task-066. Done
when `bin/adhere measure` over the task-057 fixture prints the Hexagonal
score and its findings as JSON, with every other quality as coverage
missing with its reason.
