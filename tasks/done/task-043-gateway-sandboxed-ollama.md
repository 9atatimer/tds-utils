---
id: task-043
kind: task
title: "ollama-gateway: external ollama under sandbox-exec, gated by the G4 probe"
created: 2026-10-12
issue: 363
implements: docs/design/OLLAMA-GATEWAY.DESIGN.md
---

The laptop's inference source: `lmde/components/ollama-gateway/`, the
external ollama on `127.0.0.1:<ollama-port>` (never 11434) under the
gateway's sandbox profile, started by a LaunchAgent.

Behaviors, each RED first (G4, G7, G8; Key Decisions Q3, Q7, Q10):

- The probe, run under the profile, fails when the canary under `$HOME`
  (outside both allow-listed trees) is readable, or when the run token is
  retrievable via the Security framework or `/usr/bin/security`.
- Q7, first cut: the profile denies loopback to 11434 and writes to the
  model store; the probe asserts both.
- The launcher refuses to start ollama when the probe fails; never falls
  back to unconfined (DEGRADED).
- `HOME` is the gateway config tree under `~/.local/`; store pruning off;
  one loaded model at most; short `keep_alive` (Q3).
- G8: the everyday ollama's port, plist and store contents are unchanged
  by install, run and uninstall.

Radar: `sandbox-exec` Trial row in `lmde/TECH_RADAR.md` (Key Decisions).
Spike evidence: tds-utils Issue#363 comment of 2026-10-02.
