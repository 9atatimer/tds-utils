---
id: task-047
kind: task
title: "ocr-review: reusable workflow skeleton, authorize job, caller template"
created: 2026-10-12
issue: 363
implements: docs/design/OCR-ON-DEMAND.DESIGN.md
---

`.github/workflows/ocr-review.yml` (`workflow_call`) and
`docs/ocr-review-caller.yml`. Needs no gateway; start in parallel with the
laptop work. Follow the `review-settled` precedent: logic in a script with
node tests (`test/review_settled*.test.mjs`), YAML thin.

Behaviors, RED first (G2, Non-Goals fork; Authorize job table):

- Not `/ocr`, or association not OWNER/MEMBER/COLLABORATOR -> skipped, no
  secret referenced by the job.
- Issue that is not a PR, or a closed PR -> failed `pr-not-open`.
- Head repo differs from base -> failed `fork`.
- Caller: triggers `workflow_dispatch` (pr, model) and `issue_comment`
  only; passes `OLLAMA_GATEWAY_OP_SA_TOKEN` by name; never
  `secrets: inherit`; permissions exactly contents read, pull-requests
  write, issues write.
- Runner (Key Decisions, runner row): every job `runs-on` the caller's
  `CI_RUNS_ON` when set, GitHub-hosted otherwise (tds-utils PR#436
  pattern).
