# Environment Distribution: Packages, Manifests, and One-Way Seeding

> **Status:** DRAFT
> **Date:** 2026-08-08
> **Authors:** Todd, Claude
> **Depends on:** none

---

## Overview

This repo is the running configuration of every machine it is checked out on,
which conflates three roles: source tree, build artifact, and installed
product. This design separates them: the repo's functional areas become named
**packages**, a per-device **manifest** selects packages, an **exporter**
builds a clean versioned artifact from a manifest, and an **installer**
deploys the artifact into a versioned prefix that `$HOME` symlinks point at.
Distribution is strictly one-way (authoring machine -> consuming device), so a
work machine receives an artifact -- never the repository.

---

## Goals

1. **Seed a work machine with a policy-clean subset** -- an exported artifact
   for the work manifest contains zero bytes of denied packages (verifiable:
   `tar -tzf` cross-checked against the deny list) and no git history.
2. **Decouple live config from the dev checkout** -- after install, a
   `git checkout <branch>` in the dev checkout changes nothing in any live
   shell; only `tds-install` changes live config.
3. **Package-scoped re-seeding** -- re-exporting and re-installing a single
   package (e.g. `emacs`) is one command per side and is idempotent.
4. **Rollback** -- reverting the whole environment to the previously
   installed version is a single command and survives a broken install.
5. **Self-protection** -- the exporter refuses to build an artifact that
   violates the manifest's deny list, including transitively via package
   requirements.

---

## Non-Goals

- **Back-porting work -> home.** Flow is one-way by policy; no merge or sync
  machinery in that direction, ever.
- **A general-purpose package manager.** No dependency solving beyond a flat
  `REQUIRES` check, no remote registries, no upgrades-in-place semantics.
- **Continuous sync between machines.** Seeding and re-seeding are manual,
  deliberate acts.
- **Re-architecting platform layout.** The existing `macos/` vs `bash/`
  split stays; packages reference paths as they are today.
- **Work-overlay content.** Work-authored config (e.g. work emacs porcelain)
  lives in a work-private repo and is out of scope here; this design only
  guarantees it a stable load-order hook.

---

## Architecture Overview

```
+---------------+  PR to master   +------------------+
| dev worktrees |---------------->| public repo      |
+---------------+                 | (github, master) |
                                  +------------------+
                                           |
                                           | git pull (authoring machine only)
                                           v
                                  +------------------+      +------------------+
                                  | authoring        |      | device manifest  |
                                  | checkout         |      | (per device)     |
                                  +------------------+      +------------------+
                                           |                        |
                                           +----------+-------------+
                                                      v
                                               bin/tds-export
                                                      |
                                                      v
                                      tds-env-<device>-<version>.tar.gz
                                        |                          |
                                        | (local)                  | scp / USB / AirDrop
                                        v                          v
                              +------------------+       +------------------+
                              | home machine     |       | work machine     |
                              | bin/tds-install  |       | ./install.sh     |
                              +------------------+       +------------------+
                                        |                          |
                                        v                          v
                              ~/.tds/dist/current        ~/.tds/dist/current
                                        ^                          ^
                                        |                          |
                                  $HOME symlinks             $HOME symlinks
```

The repository exists only on authoring machines. Consuming devices see
artifacts. The home machine is both author and consumer: it installs from its
own export, which is what finally fixes the live-symlink-into-checkout
problem (issue documented in AGENT.md, "This Checkout Is Live").

---

## Design

### Packages (`packages/*.pkg`)

A package is a named slice of the repo with declared install semantics. One
flat KEY=VALUE file per package, no new dependencies:

```
# packages/shell-zsh.pkg
NAME=shell-zsh
DESC="zsh startup suite (macOS)"
PATHS="macos/dot.zshenv macos/dot.zprofile macos/dot.zshrc macos/dot.alias macos/dot.env"
LINKS="~/.zshenv:macos/dot.zshenv ~/.zprofile:macos/dot.zprofile ~/.zshrc:macos/dot.zshrc ~/.alias:macos/dot.alias"
VERIFY=test/smoketest_shell_env.sh
```

```
# packages/goldfish.pkg
NAME=goldfish
DESC="github activity report"
PATHS="goldfish bin/goldfish"
BINS="bin/goldfish"
UVTOOLS="goldfish"
VERIFY=test/smoketest_goldfish
```

`.pkg` and `.manifest` files are **data, never code**. They are read by a
non-eval line parser (`while IFS='=' read ...` or awk), never `source`d --
sourcing would turn command substitution and parameter expansion in a value
into code execution. Parser contract: one `KEY=VALUE` per line; keys match
`[A-Z_]+`; values are literal strings (optional surrounding double quotes
stripped, no expansion, no substitution, no escapes); list values are
whitespace-separated; `#` starts a comment; any other line shape is a parse
error that aborts the run.

**Path ownership is exclusive**: a repo path may be claimed by at most one
package's `PATHS`. `tds-export` fails on duplicate claims. This is what makes
the deny-list artifact scan well-defined -- "path belonging to a denied
package" has exactly one answer, with no precedence rules.

Install semantics are expressed as optional **action fields**, not a single
class enum -- a package uses whichever apply:

| Field | Meaning | Installer action |
|-------|---------|------------------|
| `PATHS` | repo paths shipped in the artifact | copy into `~/.tds/dist/<ver>/` |
| `LINKS` | `target:source` pairs | symlink `$HOME` target -> `current/<source>` |
| `BINS` | executables | ensure on `$PATH` via `current/bin` |
| `UVTOOLS` | uv-managed python tools | `uv tool install` from shipped tree (lockfile pinned) |
| `SERVICES` | launchd/systemd units | copy unit, `launchctl bootstrap` (opt-in flag) |
| `INSTALL` | package-specific hook script | run after copy (e.g. git hook templates) |
| `VERIFY` | smoketest from `test/` | run post-install; failure aborts activation |
| `REQUIRES` | other package names | flat check at export time |

Initial package registry (from the functional-area map):

| Package | Action fields | Notes |
|---------|---------------|-------|
| `shell-zsh` | LINKS, VERIFY | macOS zsh suite |
| `shell-bash` | LINKS | Linux bash suite |
| `git` | LINKS, INSTALL | config + aliases + hook templates |
| `emacs` | LINKS, VERIFY | whole `emacs/` tree, one link |
| `screen` | LINKS | |
| `bin-core` | BINS | clip, pasteclip, macmd, generate-etags, pdb, monctl, timemachine-audit, ... |
| `goldfish` | BINS, UVTOOLS, VERIFY | |
| `bookmark-organizer` | BINS, UVTOOLS | + orgmarks |
| `log-hoarder` | LINKS, BINS, UVTOOLS, SERVICES, VERIFY | tmux conf + indexer + shepherd |
| `ai-agents` | LINKS, PATHS | clai.d, sandbox, ops/claude-code, agent skills |
| `lmde` | PATHS, SERVICES, VERIFY | platform contract + sync-monitor |
| `macos-apps` | BINS, SERVICES, VERIFY | mkmacapp, flip-monitor, launchd plists |
| `tiddlywiki` | PATHS | |

### Device manifests (`manifests/*.manifest`)

```
# manifests/work-mbp.manifest
DEVICE=work-mbp
PACKAGES="shell-zsh git emacs bin-core goldfish"
DENY="log-hoarder ai-agents lmde"
# DENY rationale (recorded, not parsed):
#   log-hoarder -- violates work data-retention policy
#   ai-agents   -- AI-authoring stack stays off work hardware
#   lmde        -- personal platform contract, not work's
```

`DENY` is a hard export-time assertion, not documentation: `tds-export` fails
if a denied package appears in `PACKAGES` or is pulled in via `REQUIRES`, and
after building it scans the artifact for any path belonging to a denied
package. Manifests contain only package names and a device label -- nothing
sensitive -- so they may be checked in; a device may also keep its manifest
locally (work overlay repo) without the public repo ever knowing it exists.

### Exporter (`bin/tds-export`)

```
tds-export -m manifests/work-mbp.manifest [-o outdir] [-p package ...]

  1. resolve PACKAGES (+ REQUIRES), check against DENY     -> fail on violation
     assert exclusive path ownership across all packages   -> fail on violation
  2. require clean tree on master                          -> fail otherwise
  3. copy each package's PATHS into a staging tree
  4. write ARTIFACT-MANIFEST (device, packages, version,
     source commit sha, build date)
  5. bundle install.sh (self-contained installer)
  6. tar -> tds-env-<device>-<version>.tar.gz
  7. assert: no denied package path present in the tar     -> fail on violation

  -p <name>: export only the named package(s) -- the re-seed path.
```

Version is calver from the source commit date: `v2026.08.08` (`.n` suffix on
collision). The sha in ARTIFACT-MANIFEST is the provenance record.

### Installer (`install.sh` inside the artifact; `bin/tds-install` at home)

```
  1. unpack into ~/.tds/dist/<version>/
  2. per package, in order: BINS wiring, UVTOOLS, INSTALL hooks
  3. run each package's VERIFY against the staged version   -> abort, no flip
  4. flip ~/.tds/dist/current -> <version>   (atomic: temp symlink, then
     rename(2) over current -- GNU `mv -T`, BSD `mv -h`; never `ln -sfn`,
     which unlinks first and leaves a window with no current)
  5. (re)point $HOME LINKS at current/...    (idempotent; only missing/wrong)
  6. record install in ~/.tds/dist/log

  tds-install --rollback   : flip current to previous version, re-verify
  tds-install -p <name>    : install only named package from artifact
```

Symlinks in `$HOME` point at `current/...`, so a version flip retargets every
link at once and rollback is one flip. `~/.tds/dist` keeps the last N (=3)
versions; older ones are pruned by the installer after a successful flip.

### Overlay hook (load-order contract)

Every config package's entry point ends with a fixed escape hatch, e.g.
`[[ -f ~/.tds-local/zshrc ]] && source ~/.tds-local/zshrc`; emacs init loads
`~/.tds-local/emacs/` last; gitconfig gains
`[include] path = ~/.tds-local/gitconfig`. `~/.tds-local` is device-owned
(on the work MBP, a work-private repo). This is the whole
personal/work boundary: core ships the hook, the device owns the content.

### Operational walkthrough (work MBP)

Day 0, at home:

```
$EDITOR manifests/work-mbp.manifest        # pick PACKAGES, set DENY
bin/tds-export -m manifests/work-mbp.manifest
# -> tds-env-work-mbp-v2026.08.08.tar.gz; copy to work machine (scp/USB)
```

Day 0, on the work machine:

```
brew install <prereqs>                     # emacs, uv, ... via work-approved channels
tar -xzf tds-env-work-mbp-v2026.08.08.tar.gz && cd tds-env-work-mbp-v2026.08.08
./install.sh                               # stage, VERIFY, flip current, link $HOME
git clone <work-private-overlay> ~/.tds-local
```

Steady state on the work machine is: no tds repo, no git remotes to the
personal tree; `~/.tds/dist/current` is the environment; all work-authored
config goes in `~/.tds-local` (its own work-private repo, committed and
pushed through work infrastructure).

Updating (only when wanted -- there is no auto-sync): at home,
`git pull` master, re-run `tds-export` (whole manifest, or `-p emacs` for
one package), carry the artifact over, run `./install.sh` again. The new
version stages beside the old one, VERIFY gates it, `current` flips, and
`tds-install --rollback` undoes it if the new version misbehaves.

---

## State Machine

Lifecycle of one installed version under `~/.tds/dist/`:

```
+--------+    install.sh     +--------+   VERIFY pass   +--------+
| STAGED |------------------>| TESTED |---------------->| ACTIVE |
+--------+                   +--------+    (flip)       +--------+
     |                            |                       |    ^
     |  VERIFY fail               |                 flip  |    | rollback
     v                            v                       v    |
+---------+                 +---------+               +----------+
| REJECTED| (removed)       | REJECTED|               | RETIRED  |
+---------+                 +---------+               | (kept,N) |
                                                      +----------+
```

| From | To | Trigger | Condition |
|------|----|---------|-----------|
| STAGED | TESTED | all VERIFY scripts pass | run against staged tree |
| STAGED/TESTED | REJECTED | any VERIFY fails | staged tree removed, current untouched |
| TESTED | ACTIVE | `current` flip | temp symlink + rename(2) |
| ACTIVE | RETIRED | newer version flips in | kept for rollback (last 3) |
| RETIRED | ACTIVE | `tds-install --rollback` | re-verify then flip |

---

## Data Model

```
packages/<name>.pkg          NAME, DESC, PATHS, LINKS, BINS, UVTOOLS,
                             SERVICES, INSTALL, VERIFY, REQUIRES
manifests/<device>.manifest  DEVICE, PACKAGES, DENY
artifact: ARTIFACT-MANIFEST  DEVICE, PACKAGES, VERSION, SOURCE_SHA, BUILT_AT
~/.tds/dist/                 <version>/..., current -> <version>, log
```

---

## Security Considerations

- **No repository on work hardware** -- artifacts carry no `.git`, no
  history, no branches; provenance is a recorded sha, not a remote.
- **Deny list enforced twice** -- at resolve time and by post-build artifact
  scan; a denied package cannot ship by accident (Goal 5).
- **No secrets in packages** -- packages ship what the public repo already
  publishes; the overlay (`~/.tds-local`) is where device credentials-adjacent
  config lives, and it is never exported.
- **Pinned python installs** -- UVTOOLS install from the shipped tree with
  its committed lockfile; no `curl | sh`, no unpinned fetches.
- **Services are opt-in** -- SERVICES registration requires an explicit
  installer flag; a seed never silently starts daemons on a work machine.

---

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Delivery mechanism | versioned tarball artifact, not git | one-way flow by construction; no personal history or denied content reachable from work hardware |
| Package definition | flat KEY=VALUE `.pkg` files | parsed as data by a non-eval reader (never sourced), zero new dependencies, diffable |
| Install semantics | per-package action fields | packages span classes (log-hoarder is config+tool+service); one enum could not express that |
| Live-config target | `~/.tds/dist/current` versioned prefix | atomic flip + rollback; dev checkout stops being live config |
| Pruning | manifest package selection + DENY assertion | policy enforced by tooling, not discipline; "not exported" is stronger than "not linked" |
| Divergence record | manifest per device + overlay repo | device identity and tweaks live with the device, not in the public tree |
| Verification | existing `test/` smoketests as VERIFY | they already exist per subsystem; install gets a gate for free |
| Version scheme | calver `vYYYY.MM.DD[.n]` + source sha | matches "environment snapshot" semantics better than semver |

---

## Open Questions

1. **Emacs granularity** -- `emacs` ships as one package initially. Splitting
   ai-author elisp out of `dot.emacs.d` requires the modular-loader
   restructure (own design doc); until then the work manifest gets all of
   `emacs/` or none.
2. **uv on the work machine** -- UVTOOLS assumes `uv` is present and allowed
   by work IT. Fallback if not: skip UVTOOLS packages in the work manifest.
3. **Home transition order** -- cutting the 14 existing `$HOME` links over to
   `current/` is a one-time migration; do it link-by-link or in one flip?
4. **Linux devices** -- manifest for LMDE box would exercise `SERVICES` with
   systemd units; deferred until a Linux device is actually seeded.

---

## Rejections

- **Fork the repo under the work GitHub account** -- puts personal history
  under work's org, invites IP ambiguity, adds fork-sync toil; artifacts
  achieve the same seeding with none of that.
- **Git tricks (sparse-checkout / pinned release checkout) as the mechanism**
  -- only addresses symlinked config, still lands a full git remote and
  history on work hardware, and prunes by path pattern instead of by named
  policy.
- **Append-only overlay (no packaging)** -- work divergence includes pruning
  (retention policy) and replacement, which source-at-the-end cannot express.
- **Off-the-shelf dotfile managers (stow, chezmoi, nix home-manager,
  ansible)** -- un-radared dependencies; none model the four install classes
  plus deny-list export in one tool, so custom glue remains either way; the
  glue alone is smaller.
- **Pure one-time seed with no tooling** -- identical up-front cost to the
  exporter (package selection must happen anyway) but forfeits package-scoped
  re-seeding of actively-groomed config (emacs, zsh).

---

## Future Considerations

- **Emacs modular loader** -- restructure `dot.emacs.d` into a thin loader
  over `modules/` + `~/.tds-local/emacs/`; enables sub-emacs pruning and the
  work porcelain package. Own design doc.
- **Work overlay repo layout** -- conventions for `~/.tds-local` content;
  belongs to the work side, documented there.
- **Artifact signing** -- `gpg --detach-sign` the tarball if work IT wants
  provenance beyond the recorded sha.
- **`tds-status`** -- report drift: links not pointing at `current`, active
  version vs latest export, failed VERIFY history.

---

## Related Documents

- [TEMPLATE.md](./TEMPLATE.md) -- structure followed
- [LOG-HOARDER.DESIGN.md](./LOG-HOARDER.DESIGN.md) -- the composite package
  motivating action fields
- AGENT.md ("This Checkout Is Live") -- the live-symlink problem Goal 2
  retires
