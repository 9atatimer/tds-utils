# Emacs Instance Sandbox

> **Status:** DRAFT
> **Date:** 2026-09-02
> **Authors:** Todd Stumpf, Claude Opus 5
> **Depends on:** [ENV-DISTRIBUTION.DESIGN.md](./ENV-DISTRIBUTION.DESIGN.md)

---

## Overview

`~/.emacs.d` is a symlink into the release worktree, and `package-user-dir`
derives from it, so the machine's live editor and its 40M of byte-compiled
packages live inside a git tree. Trying a config branch today means either
repointing that symlink or letting a second tree write into the first --
both of which put the one editor you need for urgent work at risk, and the
second of which blocks `tds-release`.

This design makes the live instance immutable, selects a config tree at
launch instead of by symlink, and keys every byte of emacs-written state to
a per-instance cache root outside every git tree.

---

## Goals

- **G1. Live is never mutated by an experiment** -- launching any branch
  instance leaves `~/.emacs.d`, `~/.tds/release`, and the release
  worktree's mtimes untouched. Assertable by a smoketest that snapshots
  the release worktree before and after a branch launch.
- **G2. Each instance owns its packages** -- a package installed or upgraded
  under one key is not visible to any other key. Assertable by resolving
  `package-user-dir` under two keys and confirming disjoint paths.
- **G3. No emacs-written file lands in any git tree** -- after a full session
  under any key, `git status` in that worktree is clean. This retires the
  twelve reactive `.gitignore` entries and closes #253.
- **G4. Instance identity is visible on three surfaces** -- scratch bannerlet,
  mode line, frame title. Assertable in batch by checking the three
  variables are set from one resolved key.
- **G5. Return to live costs nothing** -- no teardown, no symlink restore, no
  state to unwind. `emacs` with no arguments is live, always, and the live
  process may simply still be running.

---

## Non-Goals

- **Config decomposition into modules** -- `init.el` stays monolithic here.
  That is issue #204 and needs its own design; this work is orthogonal and
  does not block on it.
- **Sharing packages between instances** -- deliberately rejected below.
  Disk is cheaper than a poisoned live editor.
- **Managing multiple Emacs *binaries*** -- one `Emacs.app` serves every
  instance. Testing a config against a different Emacs version is a
  separate problem with a separate answer.
- **Syncing the cache across machines** -- the cache root is derived, local,
  and disposable by design. A second machine rebuilds it.
- **Seeding a new instance from live** -- see Rejections; the cold install
  is a feature.

---

## Architecture Overview

```
       LAUNCH                     CONFIG TREE                  STATE
                             (git, read-only to emacs)   (outside git, writable)

  emacs                 -->  ~/.tds/release/            -->  ~/.cache/emacs/live/
  (no args)                    emacs/dot.emacs.d/              elpa/
                                                               eln-cache/
                                                               transient/ ...

  emacs -b <topic>      -->  ~/workplace/.worktrees/    -->  ~/.cache/emacs/
                               tds-utils-<topic>/               tds-utils-<topic>/
                               emacs/dot.emacs.d/                elpa/
                                                                 eln-cache/ ...

                                     |
                                     v
                        early-init.el resolves the key
                        ONCE, before package-initialize,
                        and every path derives from it
```

The single invariant: **the config tree is an input, the cache root is the
output, and the key is the only thing connecting them.** Nothing in the
config tree is written to; nothing in the cache root is version controlled.

---

## Design

### Instance key resolution

The key is resolved exactly once, in `early-init.el`, because
`package-user-dir` must be set before `package-initialize` runs.

#### Responsibilities

| Responsibility | Details |
|----------------|---------|
| Identify the live instance | Resolve `user-emacs-directory` with `file-truename`; if it is under `file-truename` of `~/.tds/release`, the key is the literal string `live` |
| Identify a branch instance | Otherwise the key is the basename of the worktree root -- the directory two levels above `emacs/dot.emacs.d` |
| Handle an unrecognized tree | Fall back to `foreign-<8 hex of sha1 of truename>`; never error, never silently reuse another key |
| Publish the key | Set `tds-emacs-instance-key` and `tds-emacs-live-p` as the single source every other subsystem reads |

`~/.tds/release` is already the documented machine-scoped pointer to the
release worktree (`AGENT.md`, `bin/tds-release-link`), so `live` is anchored
to an existing invariant rather than a second hardcoded path.

#### Interface

```
tds-emacs-instance-key   -- string, e.g. "live" or "tds-utils-emacs-sandbox"
tds-emacs-live-p         -- boolean, non-nil only when key is exactly "live"
tds-emacs-cache-root     -- directory, <cache-base>/<key>/
```

`<cache-base>` is `$XDG_CACHE_HOME/emacs` when that variable is set,
otherwise `~/.cache/emacs`. It is a defvar, not a literal, so a machine with
a different cache policy overrides one thing.

### State redirection

Every path emacs writes to is set from `tds-emacs-cache-root`.

| Variable | Set to | Why it matters |
|----------|--------|----------------|
| `package-user-dir` | `<root>/elpa` | The 40M. Must be set in `early-init.el` |
| `native-comp-eln-load-path` | `<root>/eln-cache` first | Not exercised today (see below) but keyed now, because cross-key `.eln` reuse fails silently |
| `auto-save-list-file-prefix` | `<root>/auto-save-list/saves-` | |
| `transient-history-file` etc. | under `<root>/transient/` | |
| `projectile-known-projects-file`, `projectile-cache-file` | under `<root>/projectile/` | The pair that produced #253 |
| `lsp-session-file` | `<root>/lsp-session` | |
| `url-configuration-directory` | `<root>/url/` | Carries `network-security.data` |
| `gnutls-*`, `nsm-settings-file` | `<root>/nsm-settings` | |

**Native compilation is currently unavailable** -- this machine's Emacs 30.2
reports `native-comp-available-p` as nil and has no `eln-cache` anywhere.
The variable is keyed anyway: if the build ever changes, an unkeyed eln
cache would let one instance's compiled output be loaded by another with no
error and no indication.

The redirect must be **explicit `setq`, not a package.** See Key Decisions.

### Launcher

`bin/emacs` today is a single line:

```zsh
open /Applications/Emacs.app --args "$@"
```

That cannot serve this design for two reasons: macOS `open` on an
already-running application activates the existing instance and discards
`--args`, and there is no way to express which config tree is wanted.

#### Responsibilities

| Responsibility | Details |
|----------------|---------|
| Default to live | `emacs` with no branch flag launches against `~/.tds/release/emacs/dot.emacs.d` |
| Select a branch tree | `emacs -b <topic>` resolves `~/workplace/.worktrees/tds-utils-<topic>/emacs/dot.emacs.d` and passes it as `--init-directory` |
| Force a new process | Use `open -n`, or invoke `Emacs.app/Contents/MacOS/Emacs` directly, so a branch instance does not merely focus the live one |
| Refuse a missing tree | Exit non-zero with the resolved path when the worktree or its `emacs/dot.emacs.d` does not exist -- never fall through to live |
| Stay honest about the binary | The path to `Emacs.app` remains the one platform-specific value, overridable by env var for a Linux/LMDE port |

`--init-directory` is confirmed working on Emacs 30.2, and
`package-user-dir` follows it automatically -- verified by batch probe. That
is what makes launch-time selection viable at all.

### Server naming

`emacs/dot.emacs.d/init.el:332` calls `(server-start)` with no
`server-name`, so two running instances collide on the default socket and
`emacsclient` reaches whichever one won the race. That breaks G5 in the
most confusing way available: you type `emacsclient`, expecting live, and
land in the experiment.

`server-name` is set to `tds-emacs-instance-key`. `emacsclient -s live` is
then unambiguous, and the shell gains a matching wrapper so the common case
stays short.

### Awareness surfaces

Three surfaces, all reading `tds-emacs-instance-key` and
`tds-emacs-live-p`. None of them recompute the key.

| Surface | Live | Branch |
|---------|------|--------|
| Scratch bannerlet | `;; [OK] emacs: live` in a green foreground | `;; [!!] emacs: <key> -- NOT LIVE` block, red background face |
| Mode line | key in a neutral face | key in a loud face |
| Frame title | key | key |

The bannerlet is the in-your-face heads-up at startup; the mode line is the
constant reminder. Three mechanical constraints govern the bannerlet:

- **Every line is prefixed `;;`.** `*scratch*` starts in
  `lisp-interaction-mode`, so an unprefixed banner makes `eval-buffer`
  choke on its own greeting.
- **The face is applied by an overlay, not a text property.** Font-lock
  fontifies `;;` lines as `font-lock-comment-face` on first refontification
  and would clobber a plain `face` property. An overlay sits above
  font-lock, and has the second benefit that the red background does not
  travel when text is yanked out of scratch.
- **It is installed on scratch *creation*, not once at startup.** Killing
  `*scratch*` recreates it bare, and scratch is the buffer most likely to
  be killed and remade.

`init.el:279` sets `inhibit-startup-message t` and the config has no
dashboard, no `desktop-save-mode`, and no `initial-buffer-choice`, so
`*scratch*` genuinely is the landing buffer. If any of those three are added
later, the bannerlet needs a second home.

**Live is marked, not merely unmarked.** The tempting inversion -- leave
live undecorated so that "no marker means live" -- fails exactly when it is
needed, because absence is also what a stale config produces. With both
marked, a *missing* marker means "this emacs predates the change," which is
itself worth knowing.

`[OK]` and `[!!]` are ASCII rather than check and cross glyphs: a glyph the
frame's font does not cover renders as a tofu box, which is a worse signal
than no glyph at all. The meaning is carried by the face, which is what is
actually perceived peripherally.

---

## State Machine

An instance key moves through four states. Only `DISCARDED` is destructive,
and it destroys nothing but cache.

```
+-----------+   first launch    +----------------+   init completes   +---------+
|  ABSENT   |------------------>| BOOTSTRAPPING  |------------------->|  READY  |
+-----------+                   +----------------+                    +---------+
      ^                                                                    |
      |                       rm -rf <cache-root>/<key>                    |
      +--------------------------------------------------------------------+
```

| From | To | Trigger | Condition |
|------|----|---------|-----------|
| ABSENT | BOOTSTRAPPING | launch under a key with no cache root | config tree exists |
| BOOTSTRAPPING | READY | `use-package` `:ensure` completes for all packages | archives reachable |
| BOOTSTRAPPING | ABSENT | init aborts before any package installs | -- |
| READY | READY | ordinary use | -- |
| READY | ABSENT | `rm -rf <cache-base>/<key>` | no instance running under that key |

`BOOTSTRAPPING` costs a minute or two of MELPA downloads and byte
compilation, once per key. It is not silent: `*Compile-Log*` shows the
byte-compiler working through the package set, so the frame is visibly busy
rather than apparently hung.

**Cold bootstrap works unmodified.** `use-package` is built-in on Emacs
30.2, so `package-installed-p` returns non-nil and the
`package-refresh-contents` guard at `init.el:42` never fires on an empty
tree. `use-package-ensure-elpa` covers this: `use-package-ensure.el:172-178`
refreshes the archives and retries when a package is absent from
`package-archive-contents`. No change to `init.el` is required for this
path.

---

## Data Model

```
<cache-base>/                      $XDG_CACHE_HOME/emacs, else ~/.cache/emacs
+-- live/                          the release worktree's instance
|   +-- elpa/                      package-user-dir
|   +-- eln-cache/                 native-comp output (currently unused)
|   +-- auto-save-list/
|   +-- transient/
|   +-- projectile/
|   +-- url/                       incl. network-security.data
|   +-- lsp-session
+-- tds-utils-<topic>/             one per topic worktree, same shape
+-- foreign-<hash>/                any --init-directory not under a known root
```

Nothing here is version controlled, backed up, or synced. Every directory is
reconstructible by relaunching under its key.

---

## Security Considerations

- **A branch's `init.el` is arbitrary executable elisp.** Launching
  `emacs -b <topic>` runs whatever that branch's config says, with the
  user's full privileges. This is not new -- it is what checking out a
  branch and restarting emacs already does -- but the launcher makes it a
  one-word operation, so the rule is worth stating: only launch branches you
  or a reviewer wrote. The launcher resolves trees only under
  `~/workplace/.worktrees/`, which keeps a stray path from being run by
  accident, and does not accept an arbitrary directory.
- **Per-instance server sockets.** `server-name` keying means each instance
  has its own socket under the user's `server-socket-dir`, inheriting
  emacs's existing ownership and permission checks. No socket is shared
  between instances.
- **Cache root permissions.** `<cache-base>` is created mode 0700. It holds
  `network-security.data` and package archives, neither of which should be
  group- or world-readable.
- **No credentials move.** This design touches no secret material; the
  1Password and `gh` paths are untouched.

---

## Key Decisions

| id | Decision | Choice | Rationale |
|----|----------|--------|-----------|
| D1 | How to select a config tree | Launch-time `--init-directory` | Repointing `~/.emacs.d` mutates live, which is precisely what G1 and G5 forbid. Verified working on 30.2 with `package-user-dir` following automatically |
| D2 | What the state is keyed on | Worktree basename, not branch name | Branch names contain `/`, a branch moves under a worktree, and deriving one means shelling out to git at every startup. The repo's discipline is already one branch per worktree |
| D3 | How `live` is identified | Literal constant, anchored to `~/.tds/release` | Deriving live's key from its path would let an incidental path change silently re-key the live cache. Reuses an existing documented pointer rather than adding a second |
| D4 | Where state goes | Explicit `setq` into a keyed cache root | `no-littering` cannot solve this: it is itself installed into `package-user-dir`, so it cannot relocate `package-user-dir`, and its defaults still land inside `user-emacs-directory`. Chicken-and-egg, plus a dependency the tech radar has not seen |
| D5 | Seam for key derivation | One function, `tds-emacs--instance-key`, called once in `early-init.el` | The three awareness surfaces and every path variable read its published result. A second caller that recomputes is the drift to watch for |
| D6 | Seam for cache location | `defvar` honoring `XDG_CACHE_HOME` | The one value a differently-configured machine needs to override |
| D7 | Bare `emacsclient` target | Always `live`, never the terminal's own instance | Bare `emacsclient` reaching a branch instance is the failure this design exists to prevent, and the surprise case -- working inside a branch instance's terminal -- is one the author does not hit, since branch instances are launched to be looked at rather than edited from. `emacsclient -s <key>` remains available for the deliberate case |
| D8 | Whether new instances are seeded | No -- cold install every time | The user's call, and it improves the design: a cold install proves the branch bootstraps from nothing, which a clone from live would mask. Cost is a minute or two, once per key |
| D9 | Bannerlet face mechanism | Overlay, applied on scratch creation | Font-lock clobbers a plain `face` property on `;;` lines; a one-shot `initial-scratch-message` is lost when scratch is killed and remade |
| D10 | Status glyphs | ASCII `[OK]` / `[!!]` | An uncovered glyph renders as tofu, a worse signal than none. The face carries the meaning |
| D11 | Mode-line segment placement | Left unspecified | Trivially changed at any time, so it does not gate the design. The frame title is the surface that survives a future mode-line package replacing `mode-line-format` wholesale |
| D12 | Re-keying when a topic worktree switches branch | No -- two branches in one worktree share a cache | Accepted as a KNOWN RISK rather than solved. Package dirs are version-suffixed so coexistence is usually benign; the live hazard is an upgrade of a package the other branch depends on, since package.el picks the highest version present. Escape hatch is `rm -rf <cache-base>/<key>`, which costs one cold install |
| D13 | The twelve reactive `.gitignore` entries | Keep them | G3 should make them unnecessary, but they cost nothing and a missed redirect is better absorbed than turned into a blocked release. Retiring them is not worth the risk of discovering a gap at `tds-release` time |

---

## Open Questions

_Unresolved. The mode-line, re-keying and `.gitignore` questions were settled
into D11-D13; the release-worktree question closed when PR #260 checked those
three files in on 2026-09-07._

- **Q1. Where the bannerlet lives if the landing buffer stops being
  `*scratch*`.** `init.el` today sets `inhibit-startup-message` and has no
  dashboard, no `desktop-save-mode` and no `initial-buffer-choice`, so
  `*scratch*` genuinely is what you land in. Adopting any of those three moves
  the surface out from under the bannerlet, and nothing in the design detects
  that -- it would simply stop appearing, which is the one failure mode an
  awareness feature must not have.
- **Q2. Whether the `foreign-<hash>` fallback key should exist at all.** It
  keeps an `--init-directory` pointed somewhere unrecognized from silently
  colliding with another key, but it also means a typo produces a working
  emacs with a fresh cache rather than an error. Refusing outright may be the
  better behavior; the launcher already refuses a missing worktree.

## Rejections

- **Repoint `~/.emacs.d` per branch** -- makes "get back to live" a
  procedure with a failure mode, instead of a property that costs nothing.
- **Key on branch name** -- slashes in the path, moves under a worktree,
  and needs a git subprocess at every startup.
- **Check `elpa` into git** -- 40M of version-churning binaries, and it
  would put every experiment's package upgrades into the reviewed history.
- **Worktrees alone, with no cache keying** -- reproduces #253 in every
  worktree and re-downloads 40M per topic; and without launch-time
  selection you still end up repointing the symlink.
- **Seed a new instance by cloning live's elpa (APFS `cp -Rc`)** -- fast,
  but it masks bootstrap failures and starts every experiment from live's
  package versions.
- **`no-littering` for the state redirect** -- cannot relocate
  `package-user-dir`, because it lives in `package-user-dir`.
- **Leave live undecorated so absence means live** -- absence is also what a
  stale config produces, so the signal fails when it is needed.
- **Check and cross glyphs in the bannerlet** -- tofu boxes on any frame
  font without coverage.
- **A shared elpa with per-key overlays** -- package directories are
  version-suffixed, so sharing is mostly harmless until it is not: an
  upgrade of a package live depends on is exactly the case that must not
  leak, and it is the case an experiment is most likely to produce.

---

## Future Considerations

- **Native compilation.** If `Emacs.app` is ever replaced with a
  native-comp build, `eln-cache` keying is already in place and should need
  no design change. Worth a smoketest at that point.
- **Issue #204's module loader.** Orthogonal, and easier afterwards: a
  branch instance is the natural place to develop a module split without
  risking the live editor.
- **Linux / LMDE parity.** The launcher is macOS-shaped (`open -n`,
  `Emacs.app`). The key resolution, state redirection, and awareness
  subsystems are platform-neutral; only `bin/emacs` needs a second arm.
- **Purging the historical artifacts.** Issues #131 and #144 cover stale
  emacs cache and auto-save files already in git history. This design stops
  new ones; it does not remove old ones.

---

## Related Documents

- [ENV-DISTRIBUTION.DESIGN.md](./ENV-DISTRIBUTION.DESIGN.md) -- the `emacs`
  package ships as one tree with one link; this design changes where that
  tree's *state* goes, not how it ships
- `AGENT.md` -- the release worktree, `~/.tds/release`, and the three-branch
  discipline this design leans on
- Issue #253 -- emacs writes runtime state into the release worktree.
  Subsumed by G3
- Issue #204 -- monolithic emacs config, no module loading. Orthogonal
- Issues #131, #144 -- purge stale emacs artifacts from git history.
  Complementary
