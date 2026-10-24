---
id: task-057
kind: task
title: "adherence: the Python code model from ast and grimp"
created: 2026-10-24
issue: 592
blocked_by: [task-056]
implements: docs/design/ARCHITECTURE.ARCH-ADHERENCE.md
---
`CodeModelPort` and its Python adapter: `Unit`, `Layer`, `Region`,
`ImportEdge`, `Definition`, `Signature`, `Body`, `Reference`, `Call`,
`Access`, `Write`, `Conditional`, `Member`, `TestCase`, built from the
standard library `ast` with import resolution by grimp, over the files a
`Declaration` covers, each unit carrying its layer from the declaration's
globs, files or regions (by the fleet's `# --- Section ---` markers or by
line range). The fixture is a small copy of `chores/`'s shape under
`adherence/tests/fixtures/`, never `chores/` itself. RED first, per
member: a test that asks the adapter for that member over the fixture and
asserts the value, with the port's contract suite shared by the fake.

Radar gate: the grimp row must be on `lmde/TECH_RADAR.md` before the
adapter lands (Issue#599). Done when every `CodeModel` member the
architecture names has a test and the fake passes the same suite.
