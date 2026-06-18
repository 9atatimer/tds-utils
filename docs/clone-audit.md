# clone-audit — clone-time security audit

Automatically audit a repository for **coding-agent poisoning** and
**auto-execution hazards** right after `git clone`, *before* you run any tooling
inside it (open it with an AI agent, `npm install`, `cd` into it under direnv,
open it in an editor).

## Threat model

The dangerous gap is between *clone* and *the first thing you do in the repo*.
Cloning itself executes no repo-controlled code, but a hostile repo can
boobytrap what your tools do next:

- **Coding-agent poisoning** — hidden or malicious instructions in the files an
  AI agent auto-ingests (`CLAUDE.md`, `.cursorrules`, `AGENTS.md`, …): invisible
  / bidi-override / Unicode-tag characters, or plain prompt-injection phrasing
  that tells the agent to exfiltrate secrets or run commands.
- **Auto-execution vectors** — `.claude/` hooks/commands/permissions, MCP
  server launch commands, npm lifecycle scripts, direnv `.envrc`, VS Code /
  devcontainer / JetBrains auto-run, `.gitattributes` filter drivers, and
  `curl … | sh` one-liners.

This is a **tripwire, not a sandbox**: it catches *known* vectors and warns. A
novel vector can slip past — the real backstop is behavioral (don't run
`claude` / `npm` with blanket auto-approval in a fresh untrusted repo).

## Why a `post-checkout` hook (git has no post-clone hook)

No hook fires on `git clone` by name. But two facts combine into an effective
global hook-on-clone:

1. **`post-checkout` fires after `git clone`'s initial checkout.** It gets
   `$1`=prev-HEAD, `$2`=new-HEAD, `$3`=branch-flag, and cannot affect the
   checkout — purely advisory. On a clone, `$1` is the **null OID** (all zeros,
   40 hex for SHA-1 / 64 for SHA-256), which distinguishes it from an ordinary
   `git checkout -b`.
2. **`git config init.templateDir <dir>`** replaces git's default template;
   `git clone` runs `git init` internally, copying the template's `hooks/` into
   the new repo. So a `post-checkout` in a global template is installed into
   every repo you clone, and fires on the clone.

**Security property (load-bearing):** git **never transfers `.git/hooks` from
the remote.** A cloned repo's hooks come *solely* from our template — a hostile
repo cannot ship its own `post-checkout` to preempt ours. `core.hooksPath` is
likewise not transferred. A repo's `.gitattributes` filter is an audit
*target*, not a suppression vector (it runs only if you have `filter.<name>`
defined locally).

## Components

- `git-hooks/template/hooks/post-checkout` — clone-only trigger (`#!/bin/bash`,
  bash 3.2 / BSD-safe). Detects a fresh clone (null OID + branch flag),
  suppresses `git worktree add` (linked worktrees), honors opt-out, locates the
  scanner robustly, and **always exits 0** — it never blocks or fails a clone.
- `bin/clone-audit` — the read-only scanner. **Only reads files; never executes
  repo content.** Exit `0` clean / `2` on findings.
- `bin/install-git-hook-templates` — idempotent installer that wires the global
  config with machine-correct absolute paths.

## Install

```sh
bin/install-git-hook-templates            # init.templateDir (recommended)
bin/install-git-hook-templates -m hooksPath
bin/install-git-hook-templates -n         # dry run
```

On macOS the canonical paths are committed in `git-config/dot.gitconfig`
(symlinked to `~/.gitconfig`). On Linux/LMDE the repo lives elsewhere, so run
the installer — it computes the right absolute paths (`init.templateDir` does
**not** tilde-expand, so a committed `~/...` would silently do nothing).

The installer also sets **`audit.scannerPath`** so the hook finds `clone-audit`
even when `bin/` is not on `PATH` (IDE/GUI/script-initiated clones — the most
likely place the audit would otherwise silently skip).

## Findings

| Tag              | Meaning |
|------------------|---------|
| `AGENT-FILE`     | Agent instruction file present (review surface). Informational. |
| `HIDDEN-UNICODE` | Invisible / bidi / Unicode-tag characters. |
| `INJECTION`      | Prompt-injection / hijack phrasing. |
| `AGENT-EXEC`     | `.claude` hooks/commands/permissions, MCP launch commands. |
| `AUTORUN`        | npm lifecycle, `.envrc`, devcontainer/VS Code/JetBrains, `.gitattributes` filters, `curl\|sh`. |
| `SUBMODULE`      | Submodule URLs (informational). |
| `SECRET`         | gitleaks hits (only if `gitleaks` is on `PATH`). |

## Run by hand

```sh
clone-audit path/to/repo     # exit 0 clean, 2 on findings
clone-audit                  # current directory
```

Use it for `--bare` / `--no-checkout` clones (the hook can't fire there) and
for repos you cloned before installing.

## Opt out

```sh
git config --global audit.enabled false   # or per-invocation: TDS_CLONE_AUDIT=0
```

## Clone-variant behavior

| Variant | Hook behavior |
|---------|---------------|
| Normal clone | fires, audits |
| `--depth` (shallow) | fires, audits |
| `--no-checkout` / `-n` | fires later, on first checkout |
| `--bare` / `--mirror` | no worktree → never fires (run `clone-audit` by hand) |
| `git worktree add` | suppressed (linked worktree of your own repo) |
| `git checkout -b` | not a clone (non-null prev-HEAD) → silent |

## Tests

```sh
./test/smoketest_clone_audit.sh
```
