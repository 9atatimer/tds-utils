---
id: task-069
kind: task
title: "adherence: the TypeScript and JavaScript code model"
created: 2026-10-24
issue: 593
blocked_by: [task-061]
implements: docs/design/ARCHITECTURE.ARCH-ADHERENCE.md
---
A `CodeModelPort` adapter for TypeScript and JavaScript: the import graph
and cycles from dependency-cruiser as JSON, every other member from
ast-grep rule files the shared `astgrep` adapter owns; `Vocabulary`
entries for the options-object form of ports-as-keywords and for Vitest,
Jest and `node:test` assertions. The fixture is a small copy of
`lib/decide/`'s shape. RED first, the same per-member tests as task-057
over this fixture, then `bin/adhere measure` over `lib/decide/` itself.

Radar gate: the dependency-cruiser and ast-grep rows must be on
`lmde/TECH_RADAR.md` first (Issue#599). Architecture Q1 and Q2
(signature exactness, TypeScript types) get a Key Decisions row each
from what this task finds.
