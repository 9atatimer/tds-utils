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

Carried from task-051, whose pilot ran on one private repo only
(Nine-At-A-Time-Media/Spot-the-clone, on the runner pool):

- The first public adopter proves the GitHub-hosted path: no `op` on the
  runner, so `1password/install-cli-action` installs it (needs `gpg`,
  `unzip`).
- Provoke each G5 cause once on a real PR: connector stopped
  (`gateway-down`), an unknown model by dispatch (`model-not-found`), and
  a load slow enough to draw the 507 deadline answer (retried, or
  `cold-model`). The green pilot run drew no 507: its three gateway
  requests took about 33 s of model time in all.
- The pilot repo's census row in tds-internal's credential registry,
  which lists no seeded repo yet.

The caller every repo copies changes shape if the owner's ruling on
Issue#453 (`tools_ref`) does; get that ruling before fanning out.
