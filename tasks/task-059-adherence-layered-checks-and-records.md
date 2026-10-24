---
id: task-059
kind: task
title: "adherence: the design records as input, and the Layered checks"
created: 2026-10-24
issue: 592
blocked_by: [task-058]
implements: docs/design/ARCHITECTURE.ARCH-ADHERENCE.md
---
`RecordsPort` and its markdown adapter over markdown-it-py (reads the
Behaviors table, the Domain Language, the use-case surface and the seam
list from `docs/design/DESIGN.ARCH-ADHERENCE.md`-shaped records at a target through `RepositoryPort`),
then the Layered rule checks, RED first against `measure`:

- A behavior with no home is found
- A behavior with a home passes
- An untraceable row is a finding against the record
- A missing design record is reported
- A port in a rule is found (rule part)
- A second composition root is found
- A missing composition root is a disagreement
- An adapter constructed below the root is found
- A file out of order is found
- A one-file tool is measured

Trace's match is name plus parameter names (architecture Q1 stays open
for the keyword-only shape; record the choice in the test). Done when the
fixture's design record drives Trace and the Layered score prints.
