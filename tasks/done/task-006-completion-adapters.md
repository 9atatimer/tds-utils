---
id: task-006
kind: task
title: chores: ollama, openai-compat completion adapters and the claude-cli agent adapter
created: 2026-09-14
blocked_by: [task-005]
implements: docs/design/CHORES.DESIGN.md
---

Two `CompletionPort` adapters (ollama, openai-compat) and one `AgentPort` adapter (claude-cli) behind one registry keyed by backend `type` that also records which port a type implements; HTTP via stdlib `urllib` with a fake transport for tests; claude-cli via `ProcessPort` with the lesson-19 isolation flags, parsing JSON output for usage, turns and cost. Typed errors map from HTTP status / connection failure / exit code. Swap test: registering a fourth type touches no domain or application module. Prices from the backend table produce `usd`; absent table produces `None`.
