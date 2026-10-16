---
id: task-036
kind: bug
title: "dynomark: the "local" model mark is decided by the Ollama host alone"
created: 2026-10-05
issue: 411
implements: docs/design/DYNOMARK.DESIGN.md
---

`settings.py:297-306` marks both models local exactly when `OLLAMA_HOST` is loopback; a cloud-tagged model or a tunnel behind 127.0.0.1 reads as local, and the embedding model is never shown. Security Considerations, "Cloud model egress".

Evidence, impact and done-criteria: issue #411. Daemon paths are under
`dynomark/daemon/src/dynomark_daemon/`. RED test first (law 5).
