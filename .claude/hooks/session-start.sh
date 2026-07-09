#!/usr/bin/env bash
# SessionStart hook: refresh the published ast-mcp MCP server at USER scope
# (~/.local/bin/ast-mcp) -- the single path the committed .mcp.json names via
# "${HOME}/.local/bin/ast-mcp", that ~/.claude.json registers, and that the
# clai.d/*/pre/20-enable-ast-mcp seed hooks write.
#
# Role after #99 (RD4): this hook is the idempotent REFRESH/FALLBACK, NOT the
# first-connect installer. A SessionStart hook cannot win the startup race
# against MCP connect for the binary it installs (the client spawns .mcp.json
# servers concurrently with these hooks), so the first-connect install happens
# in the environment SETUP step (sandbox/claude-web/setup.sh), which runs
# before session init.
#
# This hook USED to install a project-local .ast-mcp/ tree that the committed
# .mcp.json pointed at. That is gone: two install sites for one server meant
# two failure modes and a permanent "Conflicting scopes" diagnostic (user and
# project scope naming different endpoints). One binary, one path, both scopes
# resolving to it -- so ast-mcp connects whether the project entry is approved
# (it shadows user scope) or not (user scope carries).
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
# classic read:packages PAT). Written under $INSTALL_DIR (~/.local, outside
# the repo -- never committed), mode 600 via umask; install_ast_mcp removes it
# right after the install so the token does not linger on disk.
write_npmrc() {
  local dir="$1" token="${GH_AI_TOOLS_PAT:-}"
  if [ -z "$token" ]; then
    note "GH_AI_TOOLS_PAT unset -- need a classic read:packages PAT to install ast-mcp from GitHub Packages"
    return 1
  fi
  mkdir -p "$dir" || return 1
  local npmrc="$dir/.npmrc"
  # Refuse to write the token through a symlink or other non-regular file at
  # the target: a stale symlink there could redirect the secret to an
  # unexpected path. And remove any pre-existing REGULAR .npmrc first, because
  # `>` truncates in place but does NOT change an existing file's mode -- the
  # umask below only governs a NEWLY created file, so a leftover mode-0644
  # .npmrc would keep 0644 and expose the token. Start fresh either way.
  if [ -L "$npmrc" ] || { [ -e "$npmrc" ] && [ ! -f "$npmrc" ]; }; then
    note "refusing to write .npmrc: $npmrc exists and is not a regular file (symlink or special)"
    return 1
  fi
  rm -f "$npmrc" || return 1
  (
    umask 077
    {
      printf '@nine-at-a-time-media:registry=https://npm.pkg.github.com\n'
      printf '//npm.pkg.github.com/:_authToken=%s\n' "$token"
    } > "$npmrc"
  ) || return 1
}

# install_ast_mcp -- install the published @nine-at-a-time-media/ast-mcp npm
# package from GitHub Packages into $INSTALL_DIR (~/.local, via -g --prefix,
# so the bin lands at $INSTALL_DIR/bin/ast-mcp). Floats to
# the latest published version (matching the previous newest-release
# behavior). Idempotent across sessions. Fails closed (returns 1) when npm is
# missing, the token/registry is unusable, or the launched bin isn't present.
install_ast_mcp() {
  command -v npm >/dev/null 2>&1 || { note "npm not on PATH -- cannot install ast-mcp"; return 1; }
  # Refuse a symlinked or non-directory INSTALL_DIR before creating/writing into
  # it: if ~/.local were pre-created as a symlink, mkdir -p would follow it and
  # write_npmrc's token could land outside the workspace. Parallels the
  # same-class guard inside write_npmrc.
  if [ -L "$INSTALL_DIR" ] || { [ -e "$INSTALL_DIR" ] && [ ! -d "$INSTALL_DIR" ]; }; then
    note "refusing to use $INSTALL_DIR: it exists and is a symlink or non-directory"
    return 1
  fi
  mkdir -p "$INSTALL_DIR" || return 1
  write_npmrc "$INSTALL_DIR" || return 1

  # -g --prefix installs into $INSTALL_DIR (~/.local), landing the executable
  # at ~/.local/bin/ast-mcp -- the single path the committed .mcp.json
  # ("${HOME}/.local/bin/ast-mcp"), ~/.claude.json, and the clai.d seed hooks
  # all name. --userconfig points npm at the authed npmrc (scope registry +
  # token). ast-mcp's own dependencies are public (registry.npmjs.org); only
  # the scoped package comes from Packages.
  # Capture npm's combined output rather than discarding it: quiet on success
  # (the log is thrown away), but on FAILURE the real reason (401/403/E404/
  # network) is echoed to the session log so a broken sandbox is debuggable --
  # not masked behind the generic note. (npm's own `--silent` is unusable here:
  # loglevel=silent suppresses errors too, so it would hide the very output we
  # need. npm redacts _authToken in its output, so the captured log is safe.)
  local rc=0 log="$INSTALL_DIR/.npm-install.log"
  npm install -g --prefix "$INSTALL_DIR" --userconfig "$INSTALL_DIR/.npmrc" \
      "@nine-at-a-time-media/ast-mcp@latest" >"$log" 2>&1 || rc=1

  # Remove the token file immediately, whatever the outcome. If the removal
  # itself fails (readonly FS, perms) the PAT would linger in the workspace --
  # surface that LOUDLY rather than silently assume it's gone. (Not a hard
  # failure: a genuinely unwritable $INSTALL_DIR would already have failed the
  # npm install above and taken the failure path, whose main() cleanup rm -rf's
  # the whole dir; refusing an otherwise-successful install over a cleanup
  # hiccup would just discard a working ast-mcp.)
  rm -f "$INSTALL_DIR/.npmrc"
  [ -e "$INSTALL_DIR/.npmrc" ] && note "WARNING: could not remove token file $INSTALL_DIR/.npmrc -- delete it manually; it must not persist in the workspace"

  if [ "$rc" -ne 0 ]; then
    note "npm install of @nine-at-a-time-media/ast-mcp failed -- ast-mcp unavailable this session."
    # Guard the log print: if npm failed so early the >"$log" redirection never
    # created the file (e.g. unwritable dir), an unguarded sed would emit a
    # misleading "can't read" and bury the real reason.
    if [ -f "$log" ]; then
      note "npm output:"
      sed 's/^/[ast-mcp hook]   /' "$log" >&2
    fi
    rm -f "$log"
    return 1
  fi
  rm -f "$log"

  # A "successful" npm install doesn't guarantee that the entrypoint which
  # .mcp.json launches actually exists (malformed package, unexpected layout).
  # Check the npm-installed BIN SHIM ($INSTALL_DIR/bin/ast-mcp) -- the
  # package.json "bin" field is the published, stable contract and the exact
  # path .mcp.json runs -- so a bad install fails closed rather than reporting
  # success while .mcp.json points at a file that isn't there.
  if [ ! -x "$AST_BIN" ]; then
    note "npm install reported success but $AST_BIN is missing or not executable -- treating as failed install"
    return 1
  fi
  note "installed @nine-at-a-time-media/ast-mcp from GitHub Packages at $AST_BIN (user scope)"
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

  INSTALL_DIR="$HOME/.local"                           # user scope, not the repo
  AST_BIN="$INSTALL_DIR/bin/ast-mcp"                   # what .mcp.json launches

  if ! install_ast_mcp; then
    # A failed refresh is NOT an outage. Unlike the old project-local
    # .ast-mcp/ tree -- which only this hook ever wrote, so a stale copy meant
    # "a binary nobody re-checked" and was deleted -- ~/.local/bin/ast-mcp is
    # installed BEFORE session init by the environment setup script
    # (sandbox/claude-web/setup.sh, RD4). That copy is this session's working
    # server and the committed .mcp.json points straight at it. Deleting it
    # because a redundant refresh could not reach the registry would take down
    # a perfectly good ast-mcp. Keep it, and say which one is being served.
    if [ -x "$AST_BIN" ]; then
      note "refresh failed, but the env-setup install at $AST_BIN is present -- serving that (no network needed this session)."
    else
      note "ast-mcp will be unavailable this session (need npm + GH_AI_TOOLS_PAT with read:packages + egress to npm.pkg.github.com and registry.npmjs.org)."
    fi
  fi
  exit 0
}

main "$@"
