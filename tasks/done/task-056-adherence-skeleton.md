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

The gate lands in this task, not with the dogfood, and it stays here
rather than in a task of its own because this task's own tests must run
in CI before they land. In order: a case in
`test/smoketest_changed_scopes.sh` that a change under `adherence/`
selects an `adherence` scope and a change elsewhere does not (RED; the
script's own header says a wrong rule skips a suite and leaves `gate`
green), then the scope in `.github/scripts/changed-scopes.sh` (`SCOPES`
and a `scopes_for` arm, with the smoketest's own scope lists and counts)
and the `changes` output in `dist-ci.yml` (GREEN), then the skeleton and
the architect tests, then the `adherence` job: `needs: changes`, the
scope's `if:`, the ubuntu leg of the `chores` job's steps (lint, format,
strict types, unit tests; task-065 adds macOS with the hook), in `gate`'s
`needs`, with the header comments of both files updated. The job runs
after the project exists because `uv sync` needs the project and pytest
fails on an empty collection. `adherence/tests/fixtures/` is excluded
from ruff, mypy and collection from the start, since task-057 puts a
deliberately flawed tree there. `changed-scopes.sh` and
`.github/workflows/` are CODEOWNERS, so this task's PR waits on the
owner; accepted. Without the job, every task from 057 to 067 would land
with `gate` green and its tests never run in CI.

Done when `bin/adhere declaration check` runs over a fixture declaration
under `adherence/tests/fixtures/`, the two architect tests are GREEN, and
the `adherence` job ran them on this task's PR head.
