---
id: task-025
kind: task
title: "dynomark phase 3a: daemon adapters -- SQLite corpus store, unix-socket transport, fetch, Ollama ports"
created: 2026-09-27
blocked_by: [task-023]
implements: docs/design/DYNOMARK.DESIGN.md
---

The daemon's edges. Each adapter is tested against the same contract
tests the task-022 fake passes (one parametrized suite, two
implementations), plus adapter-specific tests marked integration and
skipped when the dependency is absent.

1. `CorpusStorePort` on SQLite with FTS5 and `sqlite-vec`: the fake's
   contract suite passes against a temp-file database; FTS candidates and
   KNN candidates come back as two lists for the domain to fuse. Before
   the first commit here, propose the `sqlite-vec` Trial row on
   `lmde/TECH_RADAR.md` (human-maintained: propose, do not edit).
2. `TransportPort` server over a unix socket with owner-only permissions:
   the hello/version exchange, request/response by id, event replay of
   unacknowledged items on connect, batch re-offer answered from the
   client's cursor. Tested with an in-process client over a temp socket.
3. `ContentSourcePort` fetch adapter: no cookies, non-http(s) refused,
   readable-text extraction inside the adapter (library choice recorded in
   the learning checkpoint, not in the design).
4. `EmbeddingPort` and `CompletionPort` on Ollama: model id from `Config`,
   recorded alongside embeddings and placements; integration tests skip
   without a reachable Ollama.
5. Composition root: `Config` loaded once (`HostRole`, model ids, store
   path, `RetryPolicy`); a `dynomark-daemon` entry point that runs the job
   loop and the socket server; a `--check` that prints config and store
   health without touching the tree.
6. Learning checkpoint.

Acceptance: the contract suite runs green against both the fake and
SQLite; `dynomark-daemon --check` runs in the cloud sandbox with no
Ollama; no adapter type leaks into `domain/` or `app/`.
