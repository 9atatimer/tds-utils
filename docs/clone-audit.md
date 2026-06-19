# clone-audit -- runbook

Operational guide for the clone-time security audit: setup, daily use, what to
do when a finding fires, disabling, and troubleshooting.

Code:

- `bin/clone-audit` -- the scanner (read-only; never executes repo content).
- `git-hooks/template/hooks/post-checkout` -- the on-clone trigger.
- `bin/install-git-hook-templates` -- the installer.
- `test/smoketest_clone_audit.sh` -- the test suite.

---

## What it does (30-second version)

After every `git clone`, a `post-checkout` hook runs `clone-audit` against the
new working tree and prints any findings, before you run tooling inside it
(open it with an AI agent, `npm install`, `cd` under direnv, open in an editor).
It catches coding-agent poisoning (hidden/injected instructions in `CLAUDE.md`,
`.cursorrules`, etc.) and auto-execution vectors (npm lifecycle scripts,
`.claude` hooks, MCP launch commands, direnv, editor auto-run, `curl|sh`). It
only warns -- it never blocks or alters a clone. It is a tripwire, not a
sandbox: it flags known vectors; the real backstop is not running agents with
blanket auto-approval in a fresh untrusted repo.

Git has no post-clone hook; `post-checkout` fires after a clone's initial
checkout, and git never copies a remote's `.git/hooks`, so a hostile repo can't
ship a hook to suppress ours.

---

## Quick reference

| Action | Command |
|--------|---------|
| Install (this machine) | `bin/install-git-hook-templates` |
| Audit a repo by hand | `clone-audit path/to/repo` |
| Audit current dir | `clone-audit` |
| Run the tests | `./test/smoketest_clone_audit.sh` |
| Disable globally | `git config --global audit.enabled false` |
| Disable for one clone | `TDS_CLONE_AUDIT=0 git clone <url>` |
| Re-enable | `git config --global audit.enabled true` |

Exit codes: `0` clean, `2` warnings found, `1` usage error.

---

## First-time setup

The git config wiring is committed in `git-config/dot.gitconfig` (symlinked to
`~/.gitconfig`) and is **home-anchored, not absolute** -- it names only `~`
paths, so the same committed config is correct on every machine (macOS, LMDE)
no matter where this repo is checked out:

- `init.templateDir`  -> `~/.config/git/template`
- `audit.scannerPath` -> `~/.local/bin/clone-audit`
- `audit.enabled`     -> `true`

(`init.templateDir` DOES tilde-expand; the hook reads `audit.scannerPath` with
`git config --type=path` so `~` expands there too. The repo location is never
named in config.)

The one per-machine step is creating the two symlinks from those `~` paths to
this repo. Run the installer once on each machine:

```sh
bin/install-git-hook-templates
```

It creates:

- `~/.config/git/template`   -> `<repo>/git-hooks/template`
- `~/.local/bin/clone-audit` -> `<repo>/bin/clone-audit`

and sets the three config keys above, skipping any key already equal to the
desired value (so it won't rewrite the committed `dot.gitconfig` when it's
already correct; a key set to a *different* value is overwritten, with a note).

`audit.scannerPath` lets the hook find the scanner even when `bin/` isn't on
`PATH` (IDE/GUI/script-launched clones -- the case where the audit would
otherwise silently skip).

Preview without changing anything: `bin/install-git-hook-templates -n`.

---

## Verify it works

Clone a throwaway empty repo so you see the hook fire on a clean tree:

```sh
src="$(mktemp -d)"; git -C "$src" init -q && git -C "$src" commit -q --allow-empty -m init
git clone "$src" /tmp/audit-check
rm -rf "$src" /tmp/audit-check
```

You should see `post-checkout: fresh clone detected` followed by
`clone-audit: OK: no issues found`. If you don't, see Troubleshooting.

Note: auditing tds-utils itself reports findings -- from its own test
fixtures, this runbook's examples, and the scanner's own regexes. That is
expected; a pattern scanner matches the patterns it documents and tests. Don't
use this repo as your "clean" smoke test.

---

## What happens on every clone

1. `git clone` lays down the worktree and runs `post-checkout`.
2. The hook confirms it's a real clone (null previous-HEAD, not a worktree-add),
   honors opt-out, locates the scanner, and runs it.
3. `clone-audit` prints `[INFO]` lines (review surface) and `[WARN]` lines
   (potential hazards), then a one-line summary. Findings set exit code 2; the
   hook swallows that and exits 0 so the clone is never disrupted.

Example:

```
clone-audit: scanning /path/to/repo
  [INFO] AGENT-FILE    CLAUDE.md
  [WARN] INJECTION     CLAUDE.md -- matched hijack phrasing
clone-audit: WARNING: 1 warning(s) in /path/to/repo -- REVIEW before running tooling in this repo.
```

---

## A finding fired -- now what

Stop. Do not open the repo with an agent or run its install/build until you've
reviewed the flagged files by hand (read them; don't execute them).

| Tag | Means | Investigate | Decision |
|-----|-------|-------------|----------|
| `AGENT-FILE` | An agent-instruction file exists (informational). | Read it -- this is the surface poisoning hides in. | Not a warning by itself; context for the others. |
| `HIDDEN-UNICODE` | Invisible/bidi/tag characters in a text file. | Open the file in an editor that reveals them (e.g. `cat -v`, or your editor's "show invisibles"). Legit files almost never need these. | Treat as hostile unless you can explain it. |
| `INJECTION` | Hijack phrasing ("ignore previous instructions", "do not tell the user", exfiltration language). | Read the surrounding text. | Hostile if aimed at an agent; could be a false positive in security docs. |
| `AGENT-EXEC` | `.claude` hooks/commands/permissions or an MCP server launch command. | Read the JSON: what command would run, with what args, on session start? | Hostile if it runs anything you didn't expect. |
| `AUTORUN` | Runs on install/open: npm lifecycle, `.envrc`, devcontainer/VS Code/JetBrains, `.gitattributes` filter, `curl\|sh`. | Read the script/command it would execute. | Common in legit repos -- judge by what it actually runs. |
| `SUBMODULE` | Submodule URLs (informational). | Note the URLs; only fetched with `--recurse-submodules`. | Usually fine. |
| `SECRET` | gitleaks flagged possible secrets (only if `gitleaks` is installed). | Run `gitleaks detect --source <repo>` for detail. | Investigate before pushing anywhere. |

If a repo is clearly hostile: delete the clone (`rm -rf`) -- the files are inert
on disk until you act on them, so deletion is safe.

Re-run the audit anytime: `clone-audit path/to/repo`.

---

## Disable / opt out

- One clone: `TDS_CLONE_AUDIT=0 git clone <url>`
- Globally (persistent): `git config --global audit.enabled false`
- Re-enable: `git config --global audit.enabled true`

---

## Move the repo

The git config is repo-location-independent (it names only `~` paths), so it
needs no change when you relocate the repo. Only the two symlinks point at the
old location -- re-run the installer from the new location to repoint them:

```sh
cd /new/path/to/tds-utils
bin/install-git-hook-templates
```

Editing the hook itself needs no reinstall -- `init.templateDir` is copied at
clone time, so the next clone uses the current template.

---

## Uninstall

```sh
git config --global --unset init.templateDir
git config --global --unset audit.scannerPath
git config --global --unset audit.enabled
# If you installed with -m hooksPath instead:
git config --global --unset core.hooksPath
```

---

## Troubleshooting

The audit didn't run on a clone:

- Bare / mirror clone (`--bare`, `--mirror`): no worktree, so `post-checkout`
  never fires. Run `clone-audit` by hand.
- `--no-checkout` / `-n`: the hook fires later, on your first checkout.
- The `~/.config/git/template` symlink is missing (repo moved, or the installer
  was never run on this machine): the template isn't found and the audit skips.
  Re-run `bin/install-git-hook-templates`. Confirm: `ls -l ~/.config/git/template`.

`post-checkout: clone-audit not found ... skipping audit.`:

- The `~/.local/bin/clone-audit` symlink is missing or `audit.scannerPath` is
  unset. Fix: re-run `bin/install-git-hook-templates` (recreates the symlink).
  Confirm: `ls -l ~/.local/bin/clone-audit`.

False positive:

- Read the flagged file; if it's genuinely benign (e.g. a security doc that
  quotes injection phrasing), no action needed -- the audit reports, it doesn't
  quarantine. If a pattern is chronically noisy, tune it in `bin/clone-audit`
  and add/adjust a case in `test/smoketest_clone_audit.sh`.

Slow on a huge monorepo:

- The scanner prunes `node_modules`, `.git`, `vendor`, `dist`, `build`, etc.
  (see `PRUNE_DIRS` in `bin/clone-audit`). Add directories there if needed.

`required tool not found: perl` (or grep/find):

- The scanner needs `bash`, `perl`, `grep`, `find`. `gitleaks` is optional.

---

## Reference

### Findings tags

`AGENT-FILE` and `SUBMODULE` are informational (`[INFO]`). `HIDDEN-UNICODE`,
`INJECTION`, `AGENT-EXEC`, `AUTORUN`, and `SECRET` are warnings (`[WARN]`) and
set exit code 2.

### Clone-variant behavior

| Variant | Hook behavior |
|---------|---------------|
| Normal clone | fires, audits |
| `--depth` (shallow) | fires, audits |
| `--no-checkout` / `-n` | fires later, on first checkout |
| `--bare` / `--mirror` | no worktree, never fires (run `clone-audit` by hand) |
| `git worktree add` | suppressed (linked worktree of your own repo) |
| `git checkout -b` | not a clone (non-null prev-HEAD), silent |

### Config keys

| Key | Purpose |
|-----|---------|
| `init.templateDir` | Hook template copied into every clone/init. |
| `audit.scannerPath` | Home-anchored (`~/...`) path to `clone-audit`, read with `--type=path`; PATH-independent lookup. |
| `audit.enabled` | `false` disables the audit. |
| `core.hooksPath` | Alternative install (`-m hooksPath`); central hooks dir for all repos. |
