# branch-guard -- runbook

Operational guide for the branch-reuse guard: what it prevents, how the gates
work, setup, daily use, disabling, caching, and troubleshooting.

Code:

- `bin/branch-merged-check` -- the checker (queries GitHub PR state; never
  executes repo content).
- `git-hooks/template/hooks/pre-commit` -- the primary BLOCK gate.
- `git-hooks/template/hooks/post-checkout` -- the advisory WARN gate (shared
  with clone-audit).
- `bin/install-git-hook-templates` -- the installer (wires both guards).
- `test/smoketest_branch_guard.sh` -- the test suite.

---

## The problem (30-second version)

Once a branch's pull request is **merged** or **closed**, that branch name is
retired. Reusing it -- checking it back out and committing more work -- wastes
effort (the history is settled), confuses reviewers, and pollutes the graph.
The fix is to cut a fresh branch off your default branch (e.g. `main`) for new work.

The branch guard catches the mistake locally, at the two moments it matters:

- **pre-commit (BLOCK)** -- the primary, earliest gate. Before a commit lands
  on a branch with a terminal PR, the hook aborts the commit with a message.
- **post-checkout (WARN)** -- a heads-up. When you check out a retired branch,
  the hook prints a warning. It cannot block (post-checkout always exits 0), so
  it is a reminder, not a wall.

Both are **client-side git hooks: advisory and bypassable** (`git commit
--no-verify`). They stop the honest mistake, not a determined bypass. The
complementary unbypassable wall is a **server-side push ruleset** on the remote
that rejects pushes to retired branch names. GitHub has **no native "no branch
reuse" rule** -- you build that with a ruleset / branch protection or a CI
check. The client guard and a server ruleset are layers, not substitutes.

---

## Quick reference

| Action | Command |
|--------|---------|
| Install (this machine) | `bin/install-git-hook-templates` |
| Check a branch by hand | `branch-merged-check <branch>` |
| Quiet check (exit code only) | `branch-merged-check -q <branch>` |
| Run the tests | `./test/smoketest_branch_guard.sh` |
| Disable globally | `git config --global branchguard.enabled false` |
| Disable for one commit | `git commit --no-verify` |
| Disable for a shell | `TDS_BRANCH_GUARD=0` (exported) |
| Re-enable | `git config --global branchguard.enabled true` |

`branch-merged-check` exit codes: `0` a terminal (MERGED/CLOSED) PR exists ->
caller should BLOCK; `1` alive (OPEN-only or no PR) -> allow; `2` could not
determine (no `gh` / not authed / offline) -> allow, fail-open.

---

## First-time setup

The branch guard rides the same home-anchored wiring as clone-audit. The git
config is committed in `git-config/dot.gitconfig` and names only `~` paths, so
it is correct on every machine (macOS, LMDE) regardless of where this repo is
checked out:

- `init.templateDir`        -> `~/.config/git/template`
- `branchguard.checkerPath` -> `~/.local/bin/branch-merged-check`
- `branchguard.enabled`     -> `true`

(`init.templateDir` tilde-expands; the hooks read `branchguard.checkerPath`
with `git config --type=path` so `~` expands there too.)

The one per-machine step is creating the symlinks. Run the installer once on
each machine:

```sh
bin/install-git-hook-templates
```

It creates `~/.local/bin/branch-merged-check -> <repo>/bin/branch-merged-check`
(alongside the clone-audit links) and sets the two config keys above, skipping
any key already equal to the desired value.

`branchguard.checkerPath` lets the hooks find the checker even when `bin/`
isn't on `PATH` (IDE/GUI-launched commits). Preview without changing anything:
`bin/install-git-hook-templates -n`.

Requires the GitHub CLI (`gh`) authenticated (`gh auth login`). Without it the
checker returns exit 2 (undetermined) and the guard fails open -- commits are
allowed, so a missing `gh` never blocks you.

---

## How detection works

`branch-merged-check <branch>` asks GitHub for the PR(s) whose head is that
branch and reports the terminal state:

- Default path: `gh pr list --head <branch> --state all --json state,number,url`,
  emitting one `STATE NUMBER URL` line per PR (STATE in `OPEN`/`MERGED`/`CLOSED`).
- If any PR is `MERGED` or `CLOSED`, exit `0` and (unless `-q`) print one line,
  e.g. `branch 'foo' already has a MERGED PR #123 (https://...)`. `MERGED` is
  preferred over `CLOSED` when both appear.
- Only `OPEN` PRs, or none: exit `1` (alive), print nothing.
- `gh` missing / not authenticated / offline / non-zero: exit `2`
  (undetermined), one short note to stderr. The guard treats this as allow.

**Query seam (for tests).** If `TDS_BRANCHGUARD_QUERY` is set to an executable,
the checker runs `"$TDS_BRANCHGUARD_QUERY" <branch>` and reads its stdout in the
same `STATE NUMBER URL` format instead of calling `gh`. This makes the whole
guard hermetically testable with no network -- see
`test/smoketest_branch_guard.sh`.

---

## What happens on each gate

**pre-commit** (in commit order, each an early exit):

1. Mid-operation (merge/rebase/cherry-pick/bisect in progress) -> skip.
2. Detached HEAD -> skip.
3. Trunk branch (`master`/`main`/`develop`/`trunk`) -> skip.
4. Opt-out (`TDS_BRANCH_GUARD=0` or `branchguard.enabled` false) -> skip.
5. Cache lookup (see below).
6. Locate + run the checker. Terminal PR -> abort the commit (exit 1) with the
   message and this guidance: cut a fresh branch off your default branch, or bypass
   this one commit with `git commit --no-verify`. Undetermined -> fail open. Alive ->
   allow.

**post-checkout** warns only. On an ordinary branch checkout of a retired
branch it prints an ASCII warning telling you the branch is merged/closed and
you should cut a fresh branch. It never blocks and stays silent when nothing is
wrong. (Fresh clones run clone-audit instead -- the two are mutually exclusive
by the hook's prev-HEAD / branch-flag logic.)

---

## Caching

The checker calls the network; the pre-commit hook caches verdicts under
`<git-dir>/tds-branchguard/` to keep commits fast. The cache key is the branch
name percent-encoded so it is filename-safe: every `%` is encoded to `%25`
first, then every `/` to `%2F` (branch names contain slashes; filenames can't).
Encoding `%` first keeps a literal `a%2Fb` (→ `a%252Fb`) from colliding with
`a/b` (→ `a%2Fb`).

- `<key>.dead` -- a **permanent** marker (within that clone) written the first
  time a branch is found terminal. While it exists the commit is blocked
  immediately with **no network call**. A retired branch stays retired.
- `<key>.alive` -- a **TTL** marker containing the epoch of the last "alive"
  check. Within `branchguard.ttl` seconds (default `600`) the hook skips the
  network re-check; once stale it re-queries. Undetermined results write **no**
  marker, so the next commit retries.

Marker writes are atomic (temp file + `mv`) and tolerate a read-only git dir:
if the write fails the verdict is still enforced for the current commit -- the
cache is only an optimization.

---

## Disable / opt out

- One commit: `git commit --no-verify`
- One shell: `export TDS_BRANCH_GUARD=0`
- Globally (persistent): `git config --global branchguard.enabled false`
- Re-enable: `git config --global branchguard.enabled true`
- Tune the alive-cache TTL: `git config --global branchguard.ttl <seconds>`

Clearing a stale `.dead` marker (rare -- e.g. a branch name legitimately
reused after deleting the old PR): remove the file under
`<git-dir>/tds-branchguard/`.

---

## Portability notes

- Hooks use `set -uo pipefail` (**not** `-e`): a hook must never abort a commit
  by an unexpected failure. The only non-zero exit is the deliberate block.
- POSIX-safe constructs only (macOS system bash 3.2 / BSD userland and Linux):
  no `mapfile`/`readarray`, no `declare -A`, no `grep -P`, no `find -printf`,
  no `sed -i` without an arg. `date +%s` is used for the TTL cache.
- The hooks are self-contained files copied into each repo's `.git/` by the
  template mechanism; they cannot source repo files. They locate the checker
  the same way `post-checkout` locates `clone-audit`: `branchguard.checkerPath`
  git config, then `PATH`, then `~/.local/bin/branch-merged-check`.
- ASCII-only output.

---

## Troubleshooting

Commit wasn't blocked on a retired branch:

- `gh` not installed or not authenticated -> checker returns 2 (undetermined),
  guard fails open. Run `gh auth status`.
- Guard disabled (`branchguard.enabled false` or `TDS_BRANCH_GUARD=0`).
- On a trunk branch (`master`/`main`/`develop`/`trunk`) -- these are skipped.
- The `~/.local/bin/branch-merged-check` symlink is missing or the hook wasn't
  installed in this repo's `.git/hooks`. Re-run `bin/install-git-hook-templates`
  and confirm `ls -l ~/.local/bin/branch-merged-check`.

Commit blocked but the PR is genuinely still open:

- A stale `.dead` marker from an earlier terminal state. Remove it from
  `<git-dir>/tds-branchguard/` (or bypass once with `--no-verify`).

Slow commits:

- Every commit on a non-trunk feature branch may hit the network once per TTL
  window. Raise `branchguard.ttl` to widen the cache window.

---

## Reference

### Config keys

| Key | Purpose |
|-----|---------|
| `branchguard.checkerPath` | Home-anchored (`~/...`) path to `branch-merged-check`, read with `--type=path`; PATH-independent lookup. |
| `branchguard.enabled` | `false` disables both gates. |
| `branchguard.ttl` | Alive-cache TTL in seconds (default `600`). |

### Environment

| Var | Effect |
|-----|--------|
| `TDS_BRANCH_GUARD=0` | Disable both gates for the current shell. |
| `TDS_BRANCHGUARD_QUERY` | Test seam: an executable that emits `STATE NUMBER URL` lines in place of `gh`. |

### Checker exit codes

| Code | Meaning | Guard action |
|------|---------|--------------|
| `0` | Terminal PR (MERGED/CLOSED) exists | BLOCK (pre-commit) / WARN (post-checkout) |
| `1` | Alive (OPEN-only or no PR) | allow |
| `2` | Could not determine (no `gh`/offline) | allow (fail-open) |

### Gate behavior

| Situation | pre-commit | post-checkout |
|-----------|-----------|---------------|
| Terminal PR | blocks commit (exit 1) | prints warning |
| Open / no PR | allows | silent |
| Undetermined | allows (fail-open) | silent |
| Trunk branch | skipped | skipped |
| Detached HEAD | skipped | n/a |
| Mid merge/rebase | skipped | n/a |
| Opt-out set | skipped | skipped |
