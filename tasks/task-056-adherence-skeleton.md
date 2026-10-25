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
command only.

The gate lands in this task, not with the dogfood: an `adherence` scope
in `.github/scripts/changed-scopes.sh` and an `adherence` job in
`dist-ci.yml` (lint, format, strict types and unit tests, as the
`chores` job runs them) in `gate`'s `needs`. RED first: a case in
`test/smoketest_changed_scopes.sh` that a change under `adherence/`
selects the scope and a change elsewhere does not (that script's own
header says a wrong rule skips a suite and leaves `gate` green). Both
paths are CODEOWNERS, so this task's PR needs the owner's approval.
Without the job, every task from 057 to 067 would land with `gate`
green and its tests never run in CI.

Done when `bin/adhere declaration check` runs over a fixture declaration
under `adherence/tests/fixtures/`, the two architect tests are GREEN, and
the `adherence` job ran them on this task's PR head.
