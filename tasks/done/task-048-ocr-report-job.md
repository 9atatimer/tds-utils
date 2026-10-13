---
id: task-048
kind: task
title: "ocr-review: report job -- run record first, then one summary comment"
created: 2026-10-12
issue: 363
blocked_by: [task-047]
implements: docs/design/OCR-ON-DEMAND.DESIGN.md
---

Report job (no secrets), State Machine table, Data Model.

Behaviors, RED first:

- Runs after authorize and review whatever their outcome, including
  cancellation, unless skipped.
- Writes the run record (`record_version`, all Data Model fields, nulls as
  specified) to the job summary and as an artifact before commenting.
- Posts exactly one summary comment per the State Machine table (none for
  `pr-not-open`); a failed post fails the job, record intact.
- `unexpected` names the failing job and step; `cancelled` is recorded.
- PR-controlled text reaches shell only via env or files, never `${{ }}`
  in `run:`.
