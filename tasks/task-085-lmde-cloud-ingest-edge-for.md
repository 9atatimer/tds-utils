---
id: task-085
kind: task
title: "LMDE: cloud ingest edge for OTLP"
created: 2026-11-14
issue: 380
implements: docs/design/LMDE.DESIGN.md
---

Tunnel, DNS, Access app and per-component write-only service tokens (section 3.4); the edge record is tds-internal `docs/design/DESIGN.otel-ingest-infra.md`.
Then: Terraform in tds-internal (human applies), a `cloudflared` radar row and LaunchAgent here, an OTLP route on the proxy layer (`lmde/components/proxy-layer/`), Worker export config per consumer. See Issue#380.
