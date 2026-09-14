---
id: task-005
kind: task
title: chores: ports, fakes, filesystem run store and definitions loader
created: 2026-09-14
blocked_by: [task-004]
implements: docs/design/CHORES.DESIGN.md
---

Ports as Protocols: `CompletionPort`, `RunStorePort`, `ClockPort`, `ProcessPort`, `SecretsPort`, `PowerPort`, `NetworkPort`, `NotifierPort`. In-memory fakes for each. Real adapters: `FsRunStore` (run dirs, `run.json` per transition, transcript append, ledger append, notifications queue, `PAUSED`, `last_tick`, tick lock) and `DefinitionsLoader` (PyYAML front-matter, `backends.yaml`, `config.yaml`, `definition_rev` via git). Contract tests parametrized over fake and real store.
