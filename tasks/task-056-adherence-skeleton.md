---
id: task-056
kind: task
title: "adherence: the engine skeleton, its launcher, and load_declaration"
created: 2026-10-24
issue: 597
implements: docs/design/ARCHITECTURE.ARCH-ADHERENCE.md
---
The first slice of the architecture: a uv project at `adherence/` laid
out as `chores/` is (`src/adherence/{domain,application,ports,adapters,cli}`,
`container.py`, tests under `adherence/tests/`), `bin/adhere` as the
launcher `bin/chores` is, strict mypy, Ruff and pytest wired, and the
engine's own architect tests written before any check exists: an
import-direction test over `adherence/` (domain imports no port, adapter,
subprocess, fs, env or vendor; application imports no adapter) and a
composition-root test that `container.py` builds with every port faked.
Then the first use case, RED first, one behavior per commit, against
`load_declaration` by the architecture's signature:

- `load_declaration` returns `Declaration.none` for a repository with no
  `adherence.toml` (the `load_declaration` half of "An undeclared
  repository is measured"; the `measure` half is task-058)
- `load_declaration` returns `DeclarationUnreadable` for one that cannot
  be parsed (the half of "An unreadable declaration is not run" that is
  this use case's; the verdict half is task-058)
- the Declared-quality exemption refusal in `domain/declaration`
  (the validation half of "The Declared quality cannot be exempted"; its
  "reported" half is task-058)

`adherence.toml` is parsed with the standard library. `RepositoryPort`
gets its protocol, its `git` adapter for `read`, `tree` and the staged
index, and its fake. `cli/main.py` gets the thin `declaration check`
command only. Done when `bin/adhere declaration check` runs over a
fixture declaration under `adherence/tests/fixtures/` and the two
architect tests are GREEN.
