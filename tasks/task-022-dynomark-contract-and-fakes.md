---
id: task-022
kind: task
title: "dynomark phase 0: package scaffold, versioned transport contract schema, one fake per port"
created: 2026-09-27
implements: docs/design/DYNOMARK.DESIGN.md
---

Two runtimes, one language. Scaffold `dynomark/` with a daemon package and
an extension package, and the contract they share.

Stack (a planning decision, not a design one; the design leaves the daemon
language free): daemon in Python 3.11+ with uv, pytest, mypy strict and
Ruff, hexagonal layout per the style-python skill, mirroring
`bookmark-organizer/` and `log-hoarder/`; extension in TypeScript per the
style-typescript and testing-node skills. The contract is language-neutral
JSON Schema under `dynomark/contract/v1/`, validated from both sides.

```
dynomark/
  contract/v1/          message schemas + a CONTRACT_VERSION constant
  daemon/               pyproject.toml, src/dynomark_daemon/{domain,ports,app,adapters}, tests/
  extension/            package.json, src/{domain,ports,app,adapters}, tests/
```

Steps, each one commit:

1. `test(dynomark): contract schemas validate the design's message set (RED)`
   -- a test per message kind named in the design's transport contract
   (hello/version, ingest request, job event, batch offer, batch receipt,
   index pull, search, unacknowledged replay); assert each example
   document validates and a version mismatch is representable.
2. `feat(dynomark): contract v1 schemas (GREEN)`.
3. `test(dynomark-daemon): port fakes honour their contracts (RED)` -- an
   in-memory `CorpusStorePort` fake (entries, FTS candidates, KNN
   candidates, jobs, batches, snapshots, feedback), `EmbeddingPort` and
   `CompletionPort` fakes with scripted answers, a `ContentSourcePort`
   fake with `source` in {tab, fetch, none}, a `TransportPort` fake that
   records requests and replays events.
4. `feat(dynomark-daemon): port protocols and fakes (GREEN)`.
5. `test(dynomark-extension): fake tree, history and transport (RED)` --
   `BookmarkTreePort` fake over an in-memory tree with per-profile node
   ids, `HistoryPort` fake, `TransportPort` fake.
6. `feat(dynomark-extension): port interfaces and fakes (GREEN)`.
7. Learning checkpoint in `TODO_PLAN.md` Lessons (unsettled only).

Acceptance: `uv run pytest` and the extension test command are green with
no real I/O; the ubiquitous-language nouns exist as types in both
runtimes under the design's names; no adapter exists yet.

Radar: `sqlite-vec` is Assess on `lmde/TECH_RADAR.md`; this task adds no
dependency on it (task-025 does). Propose the Trial row when task-025
starts.
