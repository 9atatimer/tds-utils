---
id: task-046
kind: task
title: "ollama-gateway: bring-up remainder -- Q6 bound, G5 edge bounds, G1 on a cold OS cache"
created: 2026-10-12
issue: 363
blocked_by: [task-043, task-044, task-045]
implements: docs/design/OLLAMA-GATEWAY.DESIGN.md
---

The gateway is live through the edge since 2026-10-13: tds-internal's
`scripts/ollama-gateway/smoketest.sh` gave PASS 6/6 (G2 refusal, G1 model
list, the Q8 drift header, the G3 catch-all, a clean plan). The Q8 drift
check is built (`healthcheck.sh`, edge check) and the as-built is in
`docs/arch/`. What is not yet evidenced, all on the laptop with a human:

- Q6: measure how fast the edge answers a credentialed request once the
  laptop sleeps or goes offline (the silent-connector bound). Append the
  measured bound as a Key Decisions row to `OLLAMA-GATEWAY.DESIGN.md`,
  citing Issue#363 (the Q6 ruling: measured at bring-up and recorded).
- G5 through the edge: connector stopped -> edge 5xx within 30 s; proxy
  layer stopped -> connector 502 within 5 s. Only the route's own 503
  (ollama down: 2 ms, locally) was measured live, in PR#440.
- G1 on a cold OS cache: PR#440 proved the 507 deadline answer, the held
  load and the streaming retry with the model files in the page cache;
  a load from a cold cache (the design measured 1m48s for a ~23 GB
  model) has not been run through the route.

Record each result in `docs/ops/ollama-gateway.md` (Known gaps) and in
`docs/arch/ollama-gateway/ARCHITECTURE.md`.
