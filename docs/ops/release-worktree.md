# The release worktree -- what is live, and what is not

Moved from tds-utils `AGENT.md`, which keeps the rules every session needs and points here for the mechanics.

**The dotfiles in this repo are the running configuration of the machine you
are on -- but they go live on a release, not on a save.** `$HOME` symlinks do
not resolve into this checkout. They resolve into the `release` worktree:

```
~/.zshrc  -> ~/workplace/.worktrees/tds-utils-release/macos/dot.zshrc
~/.emacs.d -> ~/workplace/.worktrees/tds-utils-release/emacs/dot.emacs.d
```

Agent instruction files are not among them: `bin/agent-instructions` builds
each agent's file from the release worktree into
`~/.local/share/tds-utils/agents/` and owns its `$HOME` link
(`docs/ops/clai.md`).

`bin/tds-release-link` owns those links (`-n` to preview, `-r` to put them back
on the primary checkout). Run it after creating the release worktree on a new
machine; it is idempotent, and it only ever moves symlinks that already point
into one of the two checkouts.

It also maintains one pointer that is not a dotfile:

```
~/.tds/release -> ~/workplace/.worktrees/tds-utils-release
```

`PATH` and the two `dot.zshrc` source fallbacks key off that path rather than
naming the worktree, because the startup files must also work on a machine that
has no release worktree at all. Tier order, highest that exists wins:

| tier | path | owner |
|------|------|-------|
| 1 | `~/.tds/dist/current` | `bin/tds-install` -- a real dist install |
| 2 | `~/.tds/release` | `bin/tds-release-link` -- the release worktree |
| 3 | `~/workplace/tds-utils` | nobody; fresh-clone fallback, live-editable |

Tier 3 ranks last precisely because it is the one that changes under you.
`tds_path_apply` filters entries by `-d`, so a missing tier simply drops out
and a fresh clone still gets a working shell (issues #202, #235).

## Three branches, three roles

| where | branch | what it is |
|-------|--------|------------|
| `~/workplace/tds-utils` | `master` | the primary checkout: read, review, never live |
| `~/workplace/.worktrees/tds-utils-release` | `release` | what the machine is actually running |
| `~/workplace/.worktrees/tds-utils-<topic>` | `<topic>` | where you do the work |

`release` is fast-forward only and is never committed to directly. It is
always an exact commit of `master` that went through a PR -- so "what is
running" is a point on the reviewed history, never a divergent head and never
a half-finished edit.

## Two release units: public and private

`tds-release` does not know about emacs, zsh, the monitors or chores. It knows
about a **release unit**: a repo with a `release` branch, a worktree checked
out on it, a `NO.RELEASE` sentry, and a pointer under `~/.tds/`. There are two.

| unit | repo | pointer | what it carries |
|------|------|---------|-----------------|
| public | `~/workplace/tds-utils` | `~/.tds/release` | the machine's public configuration: dotfiles, `bin/`, emacs |
| private | `~/workplace/tds-internal` | `~/.tds/internal` | private machine data: manifests, routines, the chores herd |

Both go through the identical flow and the identical guards. The difference is
that **the private unit is optional**: most machines do not have that checkout,
and its absence is a one-line skip, never an error. `tds-release` ships in the
public repo and has to work on a machine that has never heard of tds-internal.

Consumers address paths *under a pointer* rather than naming a worktree --
`CHORES_HOME` is `~/.tds/internal/ops/chores`, set in `macos/dot.zshenv` when
the pointer exists. Adding the next consumer needs no change to the release
tooling, and that is the test of whether this stays one mechanism.

Why it exists at all: the chores herd was first pointed straight at
`~/workplace/tds-internal/ops/chores`, a working tree whose branch is
arbitrary. It was on an unrelated branch, so the directory did not exist and
`chores validate` reported `ok: 0 chore(s)` -- a scheduler about to be
installed against nothing. Live config must never be read out of a
branch-switchable checkout; that rule is not specific to dotfiles.

## Releasing

```zsh
bin/tds-release -n              # what would go live in every unit
bin/tds-release                 # release both units, push each
bin/tds-release <sha>           # release a specific reviewed commit (public unit)
bin/tds-release -f <sha>        # roll back (rewind release deliberately)
bin/tds-release -u private      # one unit only
bin/tds-release -u private -f <sha>   # ... including its rollback
```

That IS the install step for this machine. The moment `release` moves, the new
config is what every new shell, editor, and agent session loads. Nothing else
runs.

The post-release step also publishes the allow-listed public targets with
`bin/tds-public` (`docs/ops/tds-public.md`).

A committish argument belongs to the unit you named with `-u`, or to the public
unit when you name none; every other unit releases its own reviewed line
(`master` here, `main` in tds-internal -- `tds-release` asks each repo rather
than naming a branch).

Three refusals are worth knowing before you hit them:

- **A commit carrying `NO.RELEASE` is never released.** Everything on `master`
  is releasable by default -- that is the whole point of the branch -- so a
  commit that landed but is not yet fit to go live has to say so. Put the
  reason in the file; `tds-release` prints it back at whoever hits the refusal:

  ```zsh
  echo "held: the ledger migration must be run by hand first" > NO.RELEASE
  ```

  The gate is on the file's PRESENCE, not its contents -- `touch NO.RELEASE`
  holds a release just as firmly, and reports "(no reason recorded)". A gate
  that only fired when the file had text in it would fail open on the most
  obvious way to write one.

  There is deliberately no override. `-f` rewinds; it does not release held
  work. The way past a sentry is to remove it on `master` and release that
  commit, which leaves the decision in the history where it can be reviewed
  rather than in someone's shell.

- **The target must be an ancestor of `origin/master`.** A topic commit can be
  a perfectly clean fast-forward from `release` and still have skipped review,
  so "fast-forwardable" is not the test -- "on reviewed history" is. `-f` lifts
  the fast-forward requirement only; it does not lift this one. Merge it first.
- **The release worktree must be clean**, and that is checked before the
  already-current shortcut. A dirty release tree is a live-config problem
  whether or not `HEAD` happens to sit on the commit you asked for, so
  `tds-release` reports it rather than saying "up to date" over the top of it.
  One exception: Docker Desktop rewrites its guarded PATH line in
  `macos/dot.profile` / `macos/dot.zprofile` to an unguarded absolute-`$HOME`
  form every time it starts. A file whose only change is that rewrite is
  restored to `HEAD` (`-n` says it would) instead of refused; any other edit
  still refuses (issue #262).

One failure that is not a refusal and reads like a bug: `tds-release: fetch
failed`, preceded by `Permission denied (publickey)`. That is the 1Password SSH
agent being LOCKED -- `origin` is an SSH remote, and a locked agent still
*lists* keys while failing to sign. The global HTTPS workaround
(`git push https://github.com/...`, using gh's token) does not reach this: the
fetch happens inside `tds-release`, which names `origin`. Unlock 1Password on
the Mac and re-run. Nothing is half-done when it fails here -- it dies before
touching `release`.

## What this buys, and the one trap left

Two hazards this arrangement removes, both of which used to bite hard:

- **`git checkout <branch>` in the primary checkout no longer rewrites the
  running shell config mid-session.** It used to: a branch predating a
  `.zshenv` fix silently reinstated the bug in every shell spawned from that
  moment on, including agent tool calls, and the failure surfaced later
  somewhere unrelated.
- **Editing `macos/dot.*` no longer takes effect immediately.** A half-finished
  edit is now just an edit.

The trap that remains: **never switch branches or edit inside the release
worktree.** It is the one checkout where the old rules still apply in full --
whatever is in it is what the machine is running right now. `bin/tds-release`
refuses to release into a dirty tree for exactly this reason.

That refusal also decides WHICH files may be symlinked out of the release
worktree at all: **a file the machine writes at runtime must never be one of
them.** `~/.claude/settings.json` is the worked example -- Claude Code rewrites
it on a theme or plugin change, and `naatm-sandbox setup` rewrites its hook
registration on every cache build. Symlinked, each of those writes lands in the
release worktree and leaves it permanently dirty, so the next `bin/tds-release`
refuses. Config in that shape gets a `clai.d/<agent>/pre/` hook that jq-merges
only the keys this repo owns -- the `30-statusline` mould -- and the file itself
stays a real file in `$HOME` (issue #267).

Do topic work in its own worktree, per the global rule that worktrees live in
`~/workplace/.worktrees/<repo>-<topic>`:

```zsh
git worktree add ~/workplace/.worktrees/tds-utils-<topic> -b <branch> master
# then edit via: git -C ~/workplace/.worktrees/tds-utils-<topic> ...
```

## The global agent instruction file

`clai.d/AGENT.global.md` is the core of the global instruction file for every
agent on this machine (Claude Code, codex, opencode, omp). When it advances
the public unit, `bin/tds-release` runs the released `bin/tds-post-release`, which runs `bin/agent-instructions`, which joins it with each agent's
`clai.d/<agent>/AGENT.<agent>.md` and links the result into that agent's home
(`docs/ops/clai.md`). It is NOT this file: `AGENT.md` is repo-scoped instructions
for working in tds-utils, `AGENT.global.md` is machine-scoped instructions that
happen to be version-controlled here.

It carries the `.global` suffix so that an agent working inside `clai.d/` does
not auto-load it a second time as directory-scoped instructions.

Editing it is a PR like any other change -- which is the point. Before this it
was an untracked file in `~/.claude/`, edited in place with no review, no
history, and no way for a second machine to have the same one.

To TEST candidate shell config without installing it, point `ZDOTDIR` at a
staging directory under `env -i`. That sources your candidates while
`/etc/zshenv` and `/etc/zprofile` still run, so macOS `path_helper` stays in
the loop -- which is exactly where the interesting bugs live:

```zsh
stage=$(mktemp -d)
cp macos/dot.zshenv "$stage/.zshenv"
cp macos/dot.zprofile "$stage/.zprofile"
cp macos/dot.zshrc "$stage/.zshrc"

# .zshenv + .zprofile only -- .zshrc is NOT sourced by a non-interactive shell
env -i HOME="$HOME" ZDOTDIR="$stage" TERM=dumb /bin/zsh -lc 'command -v bash'

# adds .zshrc; a shell with no terminal or with -c never starts tmux (issue
# #427), so TMUX=probe is belt and braces, not load-bearing
env -i HOME="$HOME" ZDOTDIR="$stage" TERM=dumb TMUX=probe /bin/zsh -lic \
    'command -v bash' </dev/null
```

Match the shell shape to the file you are testing -- zsh sources a different
set for each, and a green result from the wrong shape means nothing:

| invocation | `.zshenv` | `.zprofile` | `.zshrc` |
|------------|-----------|-------------|----------|
| `zsh -c`   | yes       | no          | no       |
| `zsh -lc`  | yes       | yes         | no       |
| `zsh -ic`  | yes       | no          | yes      |
| `zsh -lic` | yes       | yes         | yes      |

Stage all three files regardless. An empty `ZDOTDIR` is not a neutral control
-- it means no dotfiles load at all, so you measure bare `path_helper` output
and conclude the config is broken when you never loaded it.

See `test/smoketest_shell_env.sh` for the worked version, and issue #176 for
what it cost to find this out.

To PROBE tmux, `-L <socket>` is not isolation: it separates the socket and
nothing else. A new server still loads `~/.tmux.conf`, whose hooks run
log-hoarder against the real `TDS_LOG_DIR`, and every server's first session
is `$0` -- so a throwaway server claims `active/$0` and sets the live
session's log tree aside (issue #503). Start probe servers with
`tmux -L <socket> -f /dev/null`, and give anything that starts one itself
(`tmux-launch`) a `HOME` with no `.tmux.conf` in it.

Note that `CLAUDE.md` is itself a symlink to `AGENT.md` -- edit `AGENT.md`.
