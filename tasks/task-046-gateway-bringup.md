---
id: task-046
kind: task
title: "ollama-gateway: bring-up -- G5 bounds, Q6 measurement, Q8 drift probe"
created: 2026-10-12
issue: 363
blocked_by: [task-043, task-044, task-045]
implements: docs/design/OLLAMA-GATEWAY.DESIGN.md
---

End-to-end on the laptop once the edge is applied.

- Q8 (a): a check that an allow-listed request through the tunnel reaches
  the deadline proxy (not some other listener on the origin port); part of
  the component's healthcheck.
- G5: connector stopped -> edge 5xx within 30 s; proxy down -> 502 within
  5 s; ollama down -> proxy 5xx within 5 s.
- Q6: measure the edge's bound for a sleeping/offline laptop; append the
  measured bound as a Key Decisions row (docs-only PR, cites Issue#363).
- G1: a cold load of the default model (`qwen3.6:latest`) gets the deadline
  answer, then a completion on retry.
- As-built for the component in `docs/arch/` at release (7a).
