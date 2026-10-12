---
id: task-052
kind: task
title: "bin/ocr-review-stats: runs by outcome and failures by cause"
created: 2026-10-12
issue: 363
blocked_by: [task-048]
implements: docs/design/OCR-ON-DEMAND.DESIGN.md
---

Read-only (G7; Design, Stats). Reads run records from adopting repos via
`gh`, reports per period runs by outcome and failures by cause, handles
every `record_version` within the 90-day retention (Q2).
