---
id: task-006
kind: task
title: chores: ollama, openai-compat and claude-cli completion adapters
created: 2026-09-14
blocked_by: [task-005]
implements: docs/design/CHORES.DESIGN.md
---

Three `CompletionPort` adapters behind one registry keyed by backend `type`; HTTP via stdlib `urllib` with a fake transport for tests; claude-cli via `ProcessPort` parsing `--output-format json` usage and cost. Typed errors map from HTTP status / connection failure / exit code. Swap test: registering a fourth type touches no domain or application module. Prices from the backend table produce `usd`; absent table produces `None`.
