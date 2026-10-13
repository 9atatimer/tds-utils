---
id: task-049
kind: task
title: "ocr-review: review job -- credentials, probe classification, upstream action, G4 verdict"
created: 2026-10-12
issue: 363
blocked_by: [task-047, task-048]
implements: docs/design/OCR-ON-DEMAND.DESIGN.md
---

Review job (Design table; G4, G5, G8).

Behaviors, RED first (fakes for 1Password and the gateway):

- Missing secret/variable, bad token, unreadable item -> `configuration`.
- Header values resolved from the item are masked before any later step.
- Probe classification per G5: Access 302/403 -> `credential`; tunnel-down
  5xx, 502, ollama-down 5xx or no HTTP answer -> `gateway-down`; non-Access
  4xx -> `model-not-found`; the deadline answer retried up to 6 min ->
  `cold-model`; anything else -> `unexpected`. Each within 1 min except the
  retry.
- Upstream `alibaba/open-code-review` action pinned by SHA, exact
  `ocr_version`, `OCR_NO_UPDATE=1`, telemetry and its own summary off,
  `pr_number` from authorize; `ocr` error -> `engine-error`.
- Verdict: reviewable files from the range minus the exclusion class; none
  reviewed -> `reviewed-nothing`; partial -> success listing the gap; none
  reviewable -> `nothing-reviewable`; missing range/reviewed list/post
  status -> `engine-error`.
- `ocr` JSON (`--audience agent`) uploaded as an artifact.

Pool ceiling: the runner pool destroys a container at 10 minutes
(tds-internal TODO_PLAN, CI Runner Pool; Issue#176). Set `timeout-minutes`
under it and measure a real review against it in task-051.

Variable naming: this record reads `OLLAMA_GATEWAY_OP_ITEM`; the tds-internal
record says callers resolve `OLLAMA_GATEWAY_OP_VAULT`. An item reference
names its vault, so one variable suffices; confirm before seeding.
