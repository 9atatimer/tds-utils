---
id: task-056
kind: task
title: "adherence: the engine skeleton, its launcher, and load_declaration"
created: 2026-10-24
issue: 597
implements: docs/design/ARCHITECTURE.ARCH-ADHERENCE.md
---
The first slice of docs/design/ARCHITECTURE.ARCH-ADHERENCE.md: a uv project at `adherence/` laid out as
`chores/` is (domain, application, ports, adapters, cli, container.py),
`bin/adhere` as the launcher `bin/chores` is, strict mypy, Ruff and pytest
wired, and the engine's own architect tests written before any check
exists: an import-direction test over `adherence/` (domain imports no
port, adapter, subprocess, fs, env or vendor; application imports no
adapter) and a composition-root test that `container.py` builds with
every port faked. Then the first use case, RED first, one behavior per
commit:

- An unreadable declaration is not run
- An undeclared repository is measured (`load_declaration` returns
  `Declaration.none`)
- The Declared quality cannot be exempted

`adherence.toml` is parsed with the standard library; `RepositoryPort`
gets its `git` adapter for `read`, `tree` and the staged index, and its
fake. Done when `bin/adhere declaration check` runs on this repository's
own `adherence.toml` (written in task-068) and the two architect tests
are in `test/`.
