---
id: task-051
kind: task
title: "ocr-review: pilot on one public and one private repo, end to end"
created: 2026-10-12
issue: 363
blocked_by: [task-046, task-049, task-050]
implements: docs/design/OCR-ON-DEMAND.DESIGN.md
---

Adopt in tds-utils (public, GitHub-hosted runner) and
Nine-At-A-Time-Media/template-tools (private, the niners pool): copy the
caller, seed, then `gh workflow run` and `/ocr` on a real PR in each.

Acceptance: every G5 cause provoked once (stop the connector, wrong model,
cold load); a successful review's findings inline; the run record readable;
wall time of a real review recorded against the pool's 10-minute ceiling.
Registry rows (tds-internal `ops/credentials/REGISTRY.md`) for each seeded
repo.
