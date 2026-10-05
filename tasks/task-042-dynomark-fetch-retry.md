---
id: task-042
kind: bug
title: "dynomark: a transient fetch failure leaves an entry with no text for good"
created: 2026-10-05
issue: 418
implements: docs/design/DYNOMARK.DESIGN.md
---

`app/capture.py:13-20` turns every ContentUnavailable, retryable or not, into source none; RetryPolicy never sees a 5xx or timeout.

Evidence, impact and done-criteria: issue #418. Daemon paths are under
`dynomark/daemon/src/dynomark_daemon/`. RED test first (law 5).
