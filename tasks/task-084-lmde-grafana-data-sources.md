---
id: task-084
kind: task
title: "LMDE: Grafana data sources, bootstrap and verify, run on the laptop"
created: 2026-11-14
---

Data sources, `setup.sh` and `test/smoketest_lmde_observability/03_verify_logs_traces.sh` are built and were verified in docker against the real images.
Done when the owner runs `setup.sh` and the three smoke tests pass on the laptop.
Local agent logs stay inert until clai sets `OTEL_LOGS_EXPORTER=otlp` (template-tools); coordinate before calling it done.
