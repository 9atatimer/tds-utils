---
id: task-053
kind: task
title: "ocr-review: adopt in every repo of both owners"
created: 2026-10-12
issue: 363
blocked_by: [task-051]
implements: docs/design/OCR-ON-DEMAND.DESIGN.md
---

Copy the caller into every repo of 9atatimer and Nine-At-A-Time-Media and
seed (G6). The repo census is `bin/per-repo`'s, not the hand-written lists
in tds-internal `ops/terraform/github/locals.tf`, which omit public repos.
One PR per repo. Registry rows per repo. `seed-ocr-review status` is the
done check: every repo present, pinned current, seeded.
