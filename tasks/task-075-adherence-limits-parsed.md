---
id: task-075
kind: bug
title: "adherence: [limits] is accepted but never parsed or applied"
created: 2026-11-06
issue: 684
blocked_by: []
implements: docs/design/ARCHITECTURE.ARCH-ADHERENCE.md
---
`[limits]` in `adherence.toml` is accepted without error but never parsed
or applied (`domain/declaration.py:31,481-486,640-692`), against A:311-312
and A:450-451. Done when tests show each named key is parsed, an unknown
key is refused, and the owning check applies the declared value in place
of its default.
