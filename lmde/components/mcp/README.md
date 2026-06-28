# LMDE Component: MCP Servers

## Overview

Guarantees that vetted, pinned [Model Context Protocol](https://modelcontextprotocol.io)
servers are installed and reachable on the host, so coding agents can assume
they exist. The contract: after `lmde sync mcp`, any agent can spawn
`ast-mcp` at the canonical absolute path `${HOME}/.local/bin/ast-mcp`
and complete an `initialize` handshake -- no per-agent install step required.

## Strategy

1. **Source**: each server ships as an npm tarball attached to a pinned GitHub
   release (e.g. `ast-mcp-v0.1.0` in the private `9atatimer/ai-tools` repo),
   fetched with `gh release download`.
2. **Versioned prefix**: the tarball is installed with
   `npm install -g --prefix $HOME/.local/share/tds-utils/mcp/<name>/<version>/`,
   so each pinned version is isolated and an upgrade never clobbers the prior one.
3. **Stable symlink**: `$HOME/.local/bin/<bin>` is (re)pointed at the active
   versioned binary. Agents reference the symlink, not the versioned path.
4. **Install vs. wiring split**:
   - **LMDE installs** the binaries, manages the symlink, health-checks each
     server, and registers them in the **Claude Desktop** config (a GUI app
     that clai cannot hook).
   - **clai hooks wire** the four clai-launched agents -- Claude Code, codex,
     opencode, and agy (Antigravity CLI) -- at agent launch time. LMDE never touches those four
     configs.

## Components

- **`servers.txt`**: pinned manifest -- one row per server
  (`name version release_tag repo bin`).
- **`lib.sh`**: sourced helpers -- `install_one_server`, `healthcheck_server`,
  `register_claude_desktop`.
- **`setup.sh`**: orchestrator -- installs each server, fails loudly if a
  handshake fails, then registers Claude Desktop.
- **`healthcheck.sh`**: per-server liveness probe (symlink + handshake);
  exits non-zero if any server is degraded.

## Conventions

- **Transport is stdio**, not network -- these servers open no ports; they are
  spawned as child processes and speak JSON-RPC over stdin/stdout.
- **Canonical invocation** in every agent config is `${HOME}/.local/bin/ast-mcp`
  with no args. The hooks (and `lib.sh`) expand `$HOME` at write time, so the
  value stored in each config is a literal per-user absolute path (e.g.
  `/Users/stumpf/.local/bin/ast-mcp` here, `/home/stumpf/...` on Linux) --
  absolute so GUI-launched agents resolve it without relying on PATH, yet
  correct for any account.
- **node-PATH for Desktop**: the installed bin has a `#!/usr/bin/env node`
  shebang. clai-launched agents inherit the shell PATH (nvm node present), so a
  bare absolute command works. **Claude Desktop** is a GUI app without nvm node
  on PATH, so its config entry pins `env.PATH` to the node bin dir (resolved at
  install time via `dirname "$(command -v node)"`) plus the system dirs.
- **Health check** is the MCP `initialize` handshake; a healthy response
  identifies the server by its logical name (`"name": "<name>"`), tolerant of
  whitespace in the JSON.

## Upgrade

1. Bump the `version` (and `release_tag`) row in `servers.txt`.
2. Run `lmde sync mcp`.

This installs the new version into a fresh prefix, repoints the symlink,
re-runs the handshake, and refreshes the Claude Desktop entry. Restart Claude
Desktop afterward; the four clai agents re-wire automatically on their next
launch.
