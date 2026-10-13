---
id: task-045
kind: task
title: "ollama-gateway: cloudflared connector LaunchAgent with a Keychain run token"
created: 2026-10-12
issue: 363
implements: docs/design/OLLAMA-GATEWAY.DESIGN.md
---

Connector daemon (Design, Connector daemon; Key Decisions Transport, Q9).

- `cloudflared` from Homebrew, transport pinned to `http2`, LaunchAgent,
  restart on crash.
- Run token read from the login Keychain at launch; never on a command line,
  in a plist or under the repo. No token -> exit non-zero naming it.
- Seeding step: an interactive human `op` session copies the
  `ollama-gateway-tunnel` item (tds-internal CONNECTOR vault) into the
  Keychain; nothing of 1Password persists afterward (Q9).
- Radar: `cloudflared` Trial row in `lmde/TECH_RADAR.md`.

Blocked outside this repo: the tunnel and its item come from tds-internal
`ops/terraform/ollama-gateway` (tds-internal TODO_PLAN, Ollama Gateway
Edge), applied by the human.
