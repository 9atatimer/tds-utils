---
id: task-044
kind: task
title: "LMDE proxy layer (HAProxy) with the gateway's deadline route"
created: 2026-10-12
issue: 363
implements: docs/design/OLLAMA-GATEWAY.DESIGN.md
---

The LMDE proxy layer does not exist yet (HAProxy is only Adopted on the
radar, PR#397). Build it with its first tenant, the gateway's route; the
layer itself has no record beyond the gateway's Deadline proxy section.

Behaviors, RED first (Deadline proxy responsibilities; Q10, Q12):

- First byte before the deadline, always: the deadline answer is a 5xx
  distinguishable by status code alone from "ollama down" and every edge or
  connector 5xx. Verify the edge's time-to-first-byte limit (~100 s) and
  set the deadline under it.
- A deadline answer does not cancel the model load (verify ollama finishes
  the load after the client closes; otherwise hold the upstream open).
- Ollama down -> 5xx within 5 s (G5).
- One loopback listener per route (Q12); listens on `127.0.0.1:<proxy-port>`
  only, forwards to `<ollama-port>` only; no throttle or payload cap.
- Neither request nor response bodies are written to disk (Q10).
- LaunchAgent, restart on crash.

`<proxy-port>` is the single source of truth that tds-internal's
`ollama-gateway` module mirrors as `origin_port`.
