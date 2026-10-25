---
id: task-067
kind: task
title: "adherence: the reusable workflow, the warehouse store and the ci-magic toolkit line"
created: 2026-10-24
issue: 598
blocked_by: [task-066]
implements: docs/design/ARCHITECTURE.ARCH-ADHERENCE.md
---
`.github/workflows/adherence.yml` on the OCR on Demand caller pattern
(`uses:` and `tools_ref` pinned together), running `bin/adhere judge
--base --head` on the caller's `CI_RUNS_ON` pool or a GitHub-hosted
runner, uploading SARIF in its own step and writing the summary; the
`warehouse` and `tiered_store` `ReportStore` adapters writing the scan
key on every run and the `by-rev/` lookup key only from the default
branch, under credentials scoped to the repository's own prefixes; the
analyzers spawned with an allowlisted environment and the judge's token
removed; and the documented `ci-magic-toolkit` manifest line. RED first
against the store adapters with a local S3-protocol fake that verifies
the signature (the data warehouse record's warning about `s3rver`), then
the workflow proven on a PR of this repository.

Radar gate: the `github/codeql-action/upload-sarif` row must be on
`lmde/TECH_RADAR.md` first (Issue#599). The bucket and its credentials
are tds-internal Issue#276; until they exist the `ci` stage falls back
to the file cache and says so. Done when one PR here shows the SARIF
annotations and the summary.
