# LMDE: Local Managed Developer Environment

The LMDE is the set of **architectural components** and services that are globally installed and managed on this machine. These components form a stable platform contract that other projects can assume is present and available.

## The Contract

Any project running within this environment can assume the existence and availability of the following "Adopted" components.

### Core Networking & Entry

- **Caddy**: The local reverse proxy and TLS terminator.
- **dnsmasq**: Local DNS orchestration for `.localhost` and internal service discovery.

### Core Infrastructure

- **1Password CLI (`op`)**: Used for secret management and identity.
- **GPG**: For commit signing and encryption.
- **NATS**: The message bus for inter-service communication (assumed on `localhost:4222`).
- **Local Container Registry**: A local mirror (on `localhost:5001`) of vetted, pinned images to ensure supply-chain resistance and offline availability.

### Management & Automation

- **gadmin**: The administrative toolkit for GitHub, issues, and environment management.

### AI Stack

- **Ollama**: Local LLM inference server.
- **remollama**: Remote Ollama orchestration and proxying.

### Development Platforms

- **kind**: Kubernetes in Docker for local cluster orchestration.

### Observability (The Stack)

- **Prometheus**: Metrics storage and querying.
- **Grafana**: Visualization and dashboards.
- **OpenTelemetry (OTel) Collector**: The unified entry point for traces and metrics (assumed on `localhost:4317` (gRPC) or `4318` (HTTP)).

---

## Residency: in-kind vs. on the host

Not every Adopted component lives inside kind. The rule:

- **Components reachable by kind-sandboxed coding agents must run inside (or be exposed into) the kind cluster.** Mac-local agents can hit either side; sandboxed agents only see what the cluster surfaces, so anything they consume needs an in-cluster path.
- Components that only serve the host edge or *feed* kind itself (Caddy, dnsmasq, the local registry) can stay outside.
- When a component's audience widens to include sandboxed agents, plan its move into the cluster.

---

## Artifact Acquisition (`lmde acquire`)

Distinct from the Adopted platform components above (kind, NATS, Caddy,
dnsmasq, the observability stack), which are laptop-only, `lmde` carries a
**cloud-portable artifact-acquisition capability**. It is the subset of `lmde`
a cloud sandbox can and should run; the platform components stay put.

`lmde acquire` installs the agent fleet's two packages from GitHub Packages
(`npm.pkg.github.com`):

- `@nine-at-a-time-media/clai` -- the CLI AI launcher / collator.
- `@nine-at-a-time-media/ast-mcp` -- the AST MCP server, landing at
  `~/.local/bin/ast-mcp`.

It owns transport, version pins, and supply-chain integrity for the fleet, and
is agent-agnostic. `--pins <file>` pins exact versions; with no `--pins` (or a
key set to UNSET/`latest`) a package floats -- acquire resolves the registry's
latest published version and installs THAT concrete version (recording it, so a
later run reinstalls on an upstream bump), never an `@latest` tag. npm
**registry integrity is always on**. Auth is a
classic `read:packages` PAT in `GH_AI_TOOLS_PAT`. Acquisition never runs a
piped install script -- it is a signed-package rail only.

Skills and the canonical MCP catalog are **NOT** separately acquired: they ride
inside the `@clai` package as bundled data (`clai/_data`), and `clai`
materializes them offline at configure time. Acquisition is therefore a
git-clone-free rail, which is exactly what fixes the Claude-web proxy block
(the proxy brokers only the session's own repo). `lmde acquire` does not mutate
any shell rc; if `~/.local/bin` is not on `$PATH` it warns.

See [../docs/design/LMDE-CLAI-BOUNDARY.DESIGN.md](../docs/design/LMDE-CLAI-BOUNDARY.DESIGN.md)
(authoritative for the acquire/configure boundary).

---

## Directory Structure

- `lmde/LMDE.md`: This document (the contract).
- `lmde/components/`: Installation, bootstrap, and health-check logic for specific components.
- `lmde/specs/`: Machine-readable specifications or manifests (e.g., kind cluster configs, NATS system accounts).

## Non-Goals (What LMDE is NOT)

- **Individual Tooling**: `fzf`, `jq`, `sed` are utilities, not architectural components.
- **Personal Configs**: Emacs `init.el`, `dot.bashrc`, and themes are personal preferences, not platform dependencies.
- **Project-Specific Services**: Databases or services that only one project needs.
- **`lmde acquire` as a platform component**: artifact acquisition is a
  cloud-portable *capability* of `lmde`, not an Adopted platform component; it
  installs agent-fleet packages, it is not a globally-managed service like
  kind or NATS.
- **Per-Project Browser Automation**: Chrome for Testing (used by some
  projects to give an agent driveable Chrome control without touching
  the user's main browser) is intentionally **per-project**, not LMDE.
  Each project installs its own under `~/.cache/<project>-cft/` with its
  own version, profile, and extension loadout. See
  `@nine-at-a-time-media/prompts` `SKILL.CHROME_MCP.md` for the pattern.

## Shell Environment (Coding Agents)

A fundamental divide exists between traditional CLI tools (like `gemini-cli`) and modern, GUI-integrated coding agents (like Antigravity or IDE extensions). When a GUI application spawns a background agent or executes a terminal command (e.g., `zsh -c "git push"`), it typically launches a **non-interactive, non-login shell**. According to `zsh` startup rules, **only `~/.zshenv` is sourced** -- `.zprofile` and `.zshrc` are completely bypassed.

To ensure LMDE agents inherit the exact same fully-hydrated toolchain as interactive terminals, the environment must be established in `.zshenv`. But `.zshenv` alone is not sufficient, and the earlier policy of moving *everything* there was wrong.

### Why `.zshenv` cannot own PATH order

On macOS, `/etc/zprofile` evaluates `/usr/libexec/path_helper -s`, and it runs **after** `~/.zshenv`. `path_helper` rebuilds `PATH` from `/etc/paths` and `/etc/paths.d` with those system directories **first**, appending the inherited `PATH` after them. Anything `.zshenv` prepended is therefore silently demoted in every login shell.

The concrete damage: `$HOMEBREW_PREFIX/bin` sinks below `/bin`, so `#!/usr/bin/env bash` resolves Apple Bash 3.2 instead of Homebrew Bash 5.x. Bash 3.2 has no `readarray`, which is what aborted the `clai` pre-hook.

The rule that follows:

> `.zshenv` can establish PATH **membership**, but it cannot establish PATH **order**. Order must be re-asserted in `.zprofile`, after `path_helper` has run.

### The three-file contract

- **`.zshenv`** -- static, silent, fork-free environment plus **the canonical PATH ordering, defined exactly once** as a function (`tds_path_apply`). Exported variables only (`NVM_DIR`, `PYENV_ROOT`, `HOMEBREW_PREFIX`, `SSH_AUTH_SOCK`). No runtime-manager startup, no completions, no output of any kind -- this file runs when zsh is a script interpreter, so one stray line on stdout corrupts whatever captured that script. Session state a caller supplied (notably `SSH_AUTH_SOCK`) must never be clobbered.
- **`.zprofile`** -- login shells only. Re-invokes `tds_path_apply` to repair the ordering `path_helper` just destroyed. It does not restate the ordering.
- **`.zshrc`** -- interactive shells only: runtime managers (`nvm`, `pyenv`, `direnv`), completion, history, prompt, tmux. Re-invokes `tds_path_apply` once after those managers, since each prepends its own entries.

Two properties make this hold together. The ordering exists in **one** place, so the three files cannot drift apart. And `tds_path_apply` is **idempotent** -- it subtracts its managed entries from wherever they currently sit and re-seats them -- which matters because `.zshrc` execs tmux, whose shell walks the entire startup sequence a second time.

Heavy initialization is banned from `.zshenv` on cost grounds: sourcing `nvm.sh` alone measures ~456ms, and every `zsh -c` an agent spawns would pay it. Where a manager's *PATH contribution* is needed without the manager, derive it statically -- nvm's default node bin directory is one file read (`$NVM_DIR/alias/default`) away.

The contract is enforced by `test/smoketest_shell_env.sh`, which stages the three dotfiles into a throwaway `ZDOTDIR` and exercises them under `env -i` in each shell shape, with `path_helper` still in the loop.
