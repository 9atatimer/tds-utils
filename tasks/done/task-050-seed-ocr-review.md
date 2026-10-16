---
id: task-050
kind: task
title: "bin/seed-ocr-review: status and seed for both owners"
created: 2026-10-12
issue: 363
implements: docs/design/OCR-ON-DEMAND.DESIGN.md
---

Seeder (Design, Seeder; G6). The `bin/seed-ci-magic` shape.

- `status`: per repo, caller present and its pinned SHA (stale pins
  flagged), secret and variables set, last run.
- `seed`: secret piped from `op read`, never an argument; variables
  `OLLAMA_GATEWAY_OP_ITEM`, `OLLAMA_GATEWAY_URL`, `OLLAMA_GATEWAY_MODEL`
  at org scope on Nine-At-A-Time-Media, per repo on 9atatimer.
- Seeding is a human act; the script is what the human runs.
- Smoketest beside `test/smoketest_seed_ci_magic.sh`.
