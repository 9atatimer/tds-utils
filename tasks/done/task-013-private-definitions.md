---
id: task-013
kind: task
title: chores: seed the private definitions repo
created: 2026-09-14
blocked_by: [task-010]
implements: docs/design/CHORES.DESIGN.md
---

In tds-internal, `ops/chores/`: `backends.yaml` (gateway as `openai-compat` with the credential reference from 1Password, local Ollama, claude-cli), `config.yaml`, and the first two chores: the `log_brander` straggler sweep migrated from `tmux_shepherd.sh` cron mode, and a daily local-model smoke. README pointing `CHORES_HOME` at the directory. Private repo because the gateway URL carries the account path.
