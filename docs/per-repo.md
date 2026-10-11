# per-repo

Run one action across every repository of a GitHub owner.
`bin/per-repo` finds the repositories and enforces the safety rules; an
action decides what is done. Test: `test/smoketest_per_repo.sh`.

```
per-repo [-o OWNER] [-v private|public|all] [-n] ACTION [ACTION-ARGS...] [-- OWNER/REPO ...]
```

## The contract an action implements

An action is any executable: a path, or `per-repo-<name>` on PATH. It is
called with the repository's facts in the environment:

| Variable | Value |
|---|---|
| `PER_REPO_MODE` | `select` or `run` |
| `PER_REPO` | `owner/name` |
| `PER_REPO_OWNER`, `PER_REPO_NAME` | the two halves |
| `PER_REPO_VISIBILITY` | `private` or `public` |
| `PER_REPO_DEFAULT_BRANCH` | e.g. `main` |
| `PER_REPO_DRY_RUN` | `1` under `-n`, else `0` |

- **select** answers whether the repository applies: exit 0 yes, 10 not
  applicable, 2 could not tell.
- **run** acts on it, with ACTION-ARGS passed through: exit 0 ok, 1 not
  ready, 2 error.

## The rules the runner enforces

- Discovery lists the owner's non-archived repositories; it never uses code
  search, an index that drops repositories (tds-utils#348). A failed listing
  runs nothing.
- Every repository is selected before any is run. One "could not tell"
  aborts the whole run with nothing changed.
- Repositories named after `--` skip discovery and the select pass.
- Exit 0 when every run is ok, 1 when some run is not ready, 2 on any error.

## Actions

### ci-runs-on

The `CI_RUNS_ON` Actions variable that moves a repository's jobs onto the
self-hosted CI runner pool. A repository applies when it is private and a
workflow mentions `vars.CI_RUNS_ON`; a public repository is refused even when
named.

```
per-repo -o 9atatimer ci-runs-on status          # readers, and the value or -
per-repo -o 9atatimer -n ci-runs-on set           # what set would do
per-repo -o 9atatimer ci-runs-on set              # set the pool labels
per-repo -o 9atatimer ci-runs-on unset -- OWNER/REPO   # rollback
```

`CI_RUNS_ON_LABELS` overrides the value, default
`["self-hosted","linux","x64","cf-pool"]`. An organization can set one
org-level variable instead; this action is for accounts without one.
