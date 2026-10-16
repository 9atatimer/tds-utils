---
id: task-041
kind: bug
title: "dynomark: receive_receipt mints an inverse batch without the host role or a profile check"
created: 2026-10-05
issue: 417
implements: docs/design/DYNOMARK.DESIGN.md
---

`app/receipt.py:90` takes no role but stores a PROPOSED inverse; `adapters/dispatch.py:631` accepts receipts on reader connections with no profile check.

Evidence, impact and done-criteria: issue #417. Daemon paths are under
`dynomark/daemon/src/dynomark_daemon/`. RED test first (law 5).
