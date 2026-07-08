#!/usr/bin/env bash
# SessionStart hook: install the published ast-mcp MCP server into a
# project-local dir so the project .mcp.json can launch it. No global install
# (AGENT.md: prefer local dependencies) -- ast-mcp lands in a gitignored,
# project-local .ast-mcp/ and the project .mcp.json launches it from there.
#
# Delivery: `npm install` from GitHub Packages (npm.pkg.github.com) -- the
# same registry the rest of the @nine-at-a-time-media fleet installs from.
# ast-mcp is built and released from nine-at-a-time-media/template-tools
# (packages/ast-mcp) and published to GitHub Packages by its release workflow.
#
# This REPLACED the previous "download the newest GitHub Release .tgz over the
# api.github.com REST API + verify a paired .sha256" delivery. In Claude Code
# web sandboxes the agent proxy blocks raw release-asset egress -- both
# api.github.com/.../releases and github.com/.../releases/download return
# synthetic errors regardless of token -- so a release-tarball path CANNOT
# work there, while the GitHub Packages npm registry IS reachable. Integrity
# is now npm's built-in registry check (every downloaded tarball is verified
# against the registry-published integrity hash) instead of a hand-fetched
# .sha256; the install still fails CLOSED (returns 1) if the bin it points
# .mcp.json at isn't present afterward.
#
# Auth: GH_AI_TOOLS_PAT -- a CLASSIC PAT with read:packages. GitHub Packages
# npm reads require the classic read:packages scope; fine-grained PATs have no
# Packages permission, and the brokered GH_TOKEN in Claude web sandboxes
# cannot read Packages either -- hence the dedicated token name.
#
# Vendoring: ast-mcp's canonical install logic lives upstream in
# template-tools; this is the tds-utils sandbox copy. Two deliberate local
# deltas: (1) the GitHub Packages delivery above (the upstream user-scope
# installer still fetches release tarballs -- reconcile there separately), and
# (2) the clai-provision branch at the top of main() (issue #84 universal
# provisioning -- see docs/design/PROVISION.DESIGN.md and sandbox/). Keep this
# copy in sync deliberately; do not let it silently drift.
#
# Synchronous on purpose: it must finish before Claude Code loads .mcp.json
# and spawns the server. Best-effort/fail-open -- if the install can't run
# (no npm, no read:packages token, no egress) it logs and exits 0 so the
# session still starts (ast-mcp is just unavailable until access is fixed).
#
# No -e: fail-open at the STEP level, not the script level. install_ast_mcp
# returns 1 on any failure and main() catches that, logs why, cleans up, and
# always exits 0 -- a broken install/network must never abort this hook and
# block the agent session from starting. If you add new top-level
# (non-function-body) commands, keep them guarded; don't add -e as a shortcut.
set -uo pipefail

# --- Action functions ---
note() { echo "[ast-mcp hook] $*" >&2; }

# write_npmrc <dir> -- write an ephemeral, authed npmrc scoping
# @nine-at-a-time-media to GitHub Packages. Token from GH_AI_TOOLS_PAT (a
# classic read:packages PAT). Written under the gitignored .ast-mcp/ (never
# committed), mode 600 via umask; install_ast_mcp removes it right after the
# install so the token does not linger in the workspace.
write_npmrc() {
  local dir="$1" token="${GH_AI_TOOLS_PAT:-}"
  if [ -z "$token" ]; then
    note "GH_AI_TOOLS_PAT unset -- need a classic read:packages PAT to install ast-mcp from GitHub Packages"
    return 1
  fi
  mkdir -p "$dir" || return 1
  (
    umask 077
    {
      printf '@nine-at-a-time-media:registry=https://npm.pkg.github.com\n'
      printf '//npm.pkg.github.com/:_authToken=%s\n' "$token"
    } > "$dir/.npmrc"
  ) || return 1
}

# install_ast_mcp -- install the published @nine-at-a-time-media/ast-mcp npm
# package from GitHub Packages into $INSTALL_DIR (local, not -g). Floats to
# the latest published version (matching the previous newest-release
# behavior). Idempotent across sessions. Fails closed (returns 1) when npm is
# missing, the token/registry is unusable, or the launched bin isn't present.
install_ast_mcp() {
  command -v npm >/dev/null 2>&1 || { note "npm not on PATH -- cannot install ast-mcp"; return 1; }
  mkdir -p "$INSTALL_DIR" || return 1
  write_npmrc "$INSTALL_DIR" || return 1

  # --prefix keeps the install project-local; --userconfig points npm at the
  # authed npmrc (scope registry + token). ast-mcp's own dependencies are
  # public (registry.npmjs.org); only the scoped package comes from Packages.
  local rc=0
  npm install --prefix "$INSTALL_DIR" --userconfig "$INSTALL_DIR/.npmrc" \
      "@nine-at-a-time-media/ast-mcp@latest" >/dev/null 2>&1 || rc=1

  # Remove the token file immediately, whatever the outcome.
  rm -f "$INSTALL_DIR/.npmrc"

  if [ "$rc" -ne 0 ]; then
    note "npm install of @nine-at-a-time-media/ast-mcp failed (missing read:packages token / registry unreachable / build error) -- ast-mcp unavailable this session"
    return 1
  fi

  # A "successful" npm install doesn't guarantee the entrypoint .mcp.json
  # launches exists (malformed package, unexpected layout). Check the
  # npm-installed BIN SHIM (node_modules/.bin/ast-mcp) -- the package.json
  # "bin" field is the published, stable contract and the exact path .mcp.json
  # runs -- so a bad install fails closed rather than reporting success while
  # .mcp.json points at a file that isn't there.
  local entry="$INSTALL_DIR/node_modules/.bin/ast-mcp"
  if [ ! -x "$entry" ]; then
    note "npm install reported success but $entry is missing or not executable -- treating as failed install"
    return 1
  fi
  note "installed @nine-at-a-time-media/ast-mcp from GitHub Packages into $INSTALL_DIR (local, not global)"
}

# --- Main ---

main() {
  # clai provision (issue #84), three-way branch per PROVISION.DESIGN.md's
  # "Session-start hook" section: clai on PATH (laptop, or a sandbox whose
  # setup script bootstrapped it) -> idempotent provisioning engine, fast
  # no-op when current, --offline-ok so no-network sessions degrade with a
  # warning instead of noise; clai absent but remote sandbox -> pinned
  # sandbox bootstrap via sandbox/provision.sh (fail-open/exit-0 by design,
  # so the session still starts on failure); else -> no-op + note. All
  # non-fatal by design; then fall through to the existing remote-gated
  # ast-mcp flow (locally the script exits at the gate below, as before).
  if command -v clai >/dev/null 2>&1; then
    note "clai found on PATH -- running clai provision (issue #84)"
    clai provision --offline-ok || note "clai provision failed (non-fatal)"
  elif [ "${CLAUDE_CODE_REMOTE:-}" = "true" ] && [ -f "${CLAUDE_PROJECT_DIR:-$PWD}/sandbox/provision.sh" ]; then
    note "clai not on PATH in remote sandbox -- running sandbox bootstrap (issue #84)"
    bash "${CLAUDE_PROJECT_DIR:-$PWD}/sandbox/provision.sh" || note "sandbox bootstrap failed (non-fatal)"
  else
    note "clai not on PATH and not a remote sandbox -- skipping provisioning"
  fi

  [ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0

  INSTALL_DIR="${CLAUDE_PROJECT_DIR:-$PWD}/.ast-mcp"   # gitignored, project-local

  if ! install_ast_mcp; then
    note "ast-mcp will be unavailable this session (need npm + GH_AI_TOOLS_PAT with read:packages + egress to npm.pkg.github.com and registry.npmjs.org)."
    # .mcp.json unconditionally points at $INSTALL_DIR's entrypoint. If a
    # PREVIOUS session's successful install is still sitting there (this
    # session resumed the same container rather than starting fresh), leaving
    # it in place would let Claude Code launch that old copy despite this
    # session being unable to confirm the install -- exactly the "stale binary
    # nobody re-checked" failure mode. Remove it so a failed install means
    # "unavailable," not "silently serve whatever was here before."
    #
    # Guard the rm -rf: INSTALL_DIR is built from an env var + $PWD, so refuse
    # to touch anything that isn't unambiguously "some path ending in our own
    # .ast-mcp directory" before deleting -- cheap insurance against ever
    # widening this to a catastrophic delete if CLAUDE_PROJECT_DIR/PWD is ever
    # empty or unexpected.
    case "$INSTALL_DIR" in
      /.ast-mcp|"") note "refusing to rm -rf suspicious INSTALL_DIR ($INSTALL_DIR)" ;;
      */.ast-mcp) rm -rf "$INSTALL_DIR" ;;
      *) note "refusing to rm -rf INSTALL_DIR, doesn't end in /.ast-mcp: $INSTALL_DIR" ;;
    esac
  fi
  exit 0
}

main "$@"
