#!/usr/bin/env bash
# setup.sh -- Claude Code web ENVIRONMENT SETUP script: runs BEFORE session
# init, installs ast-mcp so it is a CONNECTED MCP server on first load, then
# fully provisions via clai (docs/design/PROVISION.DESIGN.md, issues #99/#84).
#
# Why an env-setup script and not the SessionStart hook (RD4, #99): the MCP
# client connects to the servers in .mcp.json / ~/.claude.json CONCURRENTLY
# with the SessionStart hooks. A hook that installs the ast-mcp binary can
# never win that race for the binary it is itself installing -- first spawn
# ENOENTs, no auto-retry, and ast-mcp only connects on a later reconnect
# (observed connecting late in #99). Installing here, in the environment
# setup step that runs BEFORE session init, means the binary already exists
# when MCP first connects. The SessionStart hook remains as an idempotent
# refresh/fallback, not the first-connect installer.
#
# Install location (manual, by the human -- design non-goal to automate):
#   Claude Code web -> Environment settings -> Setup script:
#   `bash "$CLAUDE_PROJECT_DIR/sandbox/claude-web/setup.sh"`
#   (or paste this file's body). It runs from the repo checkout with the
#   environment secrets available (GH_AI_TOOLS_PAT).
#
# Registration scope (#99 decision: BOTH -- user scope primary, project
# scope fallback):
#   - USER scope (primary, race-winning, ubiquitous across repos): install
#     @nine-at-a-time-media/ast-mcp to ~/.local via `npm install -g
#     --prefix`, landing the executable at ~/.local/bin/ast-mcp -- the SAME
#     path clai's clai.d/claude/pre/20-enable-ast-mcp hook already
#     registers -- and register it in ~/.claude.json. Present before session
#     init on every repo.
#   - PROJECT scope (fallback): the committed <repo>/.mcp.json entry
#     (project-local .ast-mcp, the #98 mechanism). Best-effort pre-installed
#     here too when the checkout is reachable, so the committed entry
#     resolves at first connect rather than shadowing the user-scope server
#     with a not-yet-installed binary.
#
# Delivery / auth: `npm install` from GitHub Packages (npm.pkg.github.com)
# with a CLASSIC read:packages PAT (GH_AI_TOOLS_PAT) -- RD1/RD2. Raw release
# assets are proxy-blocked in Claude web; the Packages registry is reachable.
# Integrity is npm's built-in registry check (RD3).
#
# Fail-open: every failure logs and exits 0. A broken install/network/token
# must not block the environment or session from coming up -- it only costs
# this environment its ast-mcp/provisioning until access is fixed.
#
# No -e: fail-open at the STEP level, not the script level, like the ast-mcp
# hook and provision.sh. Keep new top-level commands guarded; do not add -e.
set -uo pipefail

# --- Action functions ---

note() { echo "[sandbox/claude-web/setup.sh] $*" >&2; }

# write_npmrc <dir> -- ephemeral, authed npmrc scoping @nine-at-a-time-media
# to GitHub Packages (classic read:packages GH_AI_TOOLS_PAT). Mode 600 via
# umask; the caller removes it right after install. Same hardened helper as
# .claude/hooks/session-start.sh and sandbox/provision.sh.
write_npmrc() {
  local dir="$1" token="${GH_AI_TOOLS_PAT:-}"
  if [ -z "$token" ]; then
    note "GH_AI_TOOLS_PAT unset -- need a classic read:packages PAT to install ast-mcp from GitHub Packages"
    return 1
  fi
  mkdir -p "$dir" || return 1
  local npmrc="$dir/.npmrc"
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

# npm_install_at <prefix> <global?> <spec> -- run one authed npm install into
# <prefix>, writing/removing the token npmrc around it and surfacing npm's
# output on failure. <global?> is "global" for `-g --prefix` (bins land in
# <prefix>/bin) or "local" for a project-local install (bins land in
# <prefix>/node_modules/.bin). Returns npm's success/failure; does NOT verify
# the resulting bin (callers do, since the expected path differs by mode).
npm_install_at() {
  local prefix="$1" mode="$2" spec="$3" rc=0
  command -v npm >/dev/null 2>&1 || { note "npm not on PATH -- cannot install $spec"; return 1; }
  if [ -L "$prefix" ] || { [ -e "$prefix" ] && [ ! -d "$prefix" ]; }; then
    note "refusing to use $prefix: it exists and is a symlink or non-directory"
    return 1
  fi
  mkdir -p "$prefix" || return 1
  write_npmrc "$prefix" || return 1
  local log="$prefix/.npm-install.log" gflag=()
  [ "$mode" = "global" ] && gflag=(-g)
  npm install "${gflag[@]}" --prefix "$prefix" --userconfig "$prefix/.npmrc" \
      "$spec" >"$log" 2>&1 || rc=1
  # If removal fails, the PAT would linger on disk under $prefix (e.g. ~/.local
  # or <repo>/.ast-mcp). Blank it best-effort and FAIL (return 1) rather than
  # proceed with a lingering credential -- this runs automatically with a
  # secret present; the caller stays fail-open at the session level.
  rm -f "$prefix/.npmrc"
  if [ -e "$prefix/.npmrc" ]; then
    : > "$prefix/.npmrc" 2>/dev/null
    rm -f "$log"
    note "ERROR: could not remove token file $prefix/.npmrc -- blanked its contents best-effort; delete it manually. Failing the install so we do not continue with a lingering credential."
    return 1
  fi
  if [ "$rc" -ne 0 ]; then
    note "npm install of $spec into $prefix failed."
    if [ -f "$log" ]; then
      note "npm output:"
      sed 's|^|[sandbox/claude-web/setup.sh]   |' "$log" >&2
    fi
    rm -f "$log"
    return 1
  fi
  rm -f "$log"
}

# install_ast_mcp_user -- USER-scope install: @nine-at-a-time-media/ast-mcp
# into ~/.local (global npm), yielding the executable at ~/.local/bin/ast-mcp.
# Echoes that bin path on success. Fails closed if the bin is absent after.
install_ast_mcp_user() {
  local prefix="$HOME/.local" bin="$HOME/.local/bin/ast-mcp"
  npm_install_at "$prefix" global "@nine-at-a-time-media/ast-mcp@latest" || return 1
  if [ ! -x "$bin" ]; then
    note "npm install reported success but $bin is missing or not executable -- treating as failed install"
    return 1
  fi
  note "installed @nine-at-a-time-media/ast-mcp at user scope ($bin)"
  printf '%s\n' "$bin"
}

# register_user_scope <bin> -- register ast-mcp in ~/.claude.json at the given
# absolute bin path and clear "ast-mcp" from every project's
# disabledMcpServers, so it is enabled everywhere. Idempotent. Preserves all
# other keys. Creates ~/.claude.json if absent; refuses to clobber an existing
# file that is not valid JSON, and refuses to touch it at all when it is a
# symlink or other non-regular file (fail-open). Uses python3 (ubiquitous in
# web sandboxes); falls back to jq.
register_user_scope() {
  local bin="$1" cfg="$HOME/.claude.json"
  # Refuse to rewrite ~/.claude.json through a symlink or non-regular file
  # (FIFO/device): this runs automatically with a token in the environment,
  # and a symlink could redirect the write while a FIFO could block on open.
  # Mirrors the .npmrc / install-dir hardening elsewhere in this script. An
  # absent file is fine (we create it).
  if [ -L "$cfg" ] || { [ -e "$cfg" ] && [ ! -f "$cfg" ]; }; then
    note "refusing to register ast-mcp: $cfg exists and is not a regular file (symlink or special); leaving it untouched"
    return 1
  fi
  if command -v python3 >/dev/null 2>&1; then
    AST_BIN="$bin" CLAUDE_JSON="$cfg" python3 - <<'PY'
import json, os, sys, tempfile
cfg = os.environ["CLAUDE_JSON"]
binpath = os.environ["AST_BIN"]
data = {}
if os.path.exists(cfg):
    try:
        with open(cfg) as f:
            text = f.read().strip()
        data = json.loads(text) if text else {}
    except (ValueError, OSError) as e:
        sys.stderr.write("[sandbox/claude-web/setup.sh] refusing to rewrite %s: not valid JSON (%s)\n" % (cfg, e))
        sys.exit(2)
    if not isinstance(data, dict):
        sys.stderr.write("[sandbox/claude-web/setup.sh] refusing to rewrite %s: top level is not an object\n" % cfg)
        sys.exit(2)
servers = data.get("mcpServers")
if not isinstance(servers, dict):
    servers = {}
servers["ast-mcp"] = {"command": binpath, "args": []}
data["mcpServers"] = servers
projects = data.get("projects")
if isinstance(projects, dict):
    for proj in projects.values():
        if isinstance(proj, dict) and isinstance(proj.get("disabledMcpServers"), list):
            proj["disabledMcpServers"] = [s for s in proj["disabledMcpServers"] if s != "ast-mcp"]
d = os.path.dirname(cfg) or "."
fd, tmp = tempfile.mkstemp(prefix=".claude.json.", dir=d)
try:
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, cfg)
except Exception:
    try:
        os.unlink(tmp)
    except OSError:
        pass
    raise
PY
    local rc=$?
    if [ "$rc" -eq 0 ]; then
      note "registered ast-mcp at user scope in $cfg -> $bin"
      return 0
    fi
    [ "$rc" -eq 2 ] && return 1   # refused to clobber; already logged
    note "python3 failed to update $cfg"
    return 1
  fi
  if command -v jq >/dev/null 2>&1; then
    [ -f "$cfg" ] || printf '{}\n' > "$cfg"
    local tmp
    tmp="$(mktemp "${cfg}.XXXXXX")" || return 1
    # Type-guard every access: this is a best-effort fallback, so a
    # malformed ~/.claude.json (mcpServers/projects/disabledMcpServers set to
    # an unexpected type) must not make jq error out. Coerce non-object
    # mcpServers/projects to {}, and only subtract from disabledMcpServers
    # when it is actually an array on an object-typed project. (A valid-JSON
    # but non-object top level still errors -> tmp stays empty -> the
    # `jq empty` guard below fails -> return 1 without clobbering.) Mirrors
    # the python3 path's defensiveness above.
    if jq --arg cmd "$bin" '
        .mcpServers = (if (.mcpServers | type) == "object" then .mcpServers else {} end) |
        .mcpServers["ast-mcp"] = {command: $cmd, args: []} |
        .projects = (if (.projects | type) == "object" then .projects else {} end) |
        .projects |= map_values(
            if (type == "object" and (.disabledMcpServers | type) == "array") then
                .disabledMcpServers = (.disabledMcpServers - ["ast-mcp"])
            else . end
        )
      ' "$cfg" > "$tmp" 2>/dev/null && jq empty "$tmp" >/dev/null 2>&1; then
      mv -f "$tmp" "$cfg"
      note "registered ast-mcp at user scope in $cfg -> $bin (jq)"
      return 0
    fi
    rm -f "$tmp"
    note "jq failed to update $cfg"
    return 1
  fi
  note "neither python3 nor jq on PATH -- cannot register ast-mcp in $cfg; the binary is installed but not registered at user scope"
  return 1
}

# resolve_project_dir -- the repo checkout to pre-install project-scope into:
# CLAUDE_PROJECT_DIR if it carries a committed .mcp.json, else the cwd if it
# does. Empty when no project .mcp.json is reachable (user scope then carries
# first connect alone).
resolve_project_dir() {
  local d
  for d in "${CLAUDE_PROJECT_DIR:-}" "$PWD"; do
    [ -n "$d" ] && [ -f "$d/.mcp.json" ] && { printf '%s\n' "$d"; return 0; }
  done
  return 1
}

# install_ast_mcp_project <dir> -- PROJECT-scope fallback: install ast-mcp
# into <dir>/.ast-mcp (project-local, matching the committed .mcp.json path)
# so the committed entry resolves at first connect. Best-effort; fail-open.
install_ast_mcp_project() {
  local dir="$1" prefix="$1/.ast-mcp" bin="$1/.ast-mcp/node_modules/.bin/ast-mcp"
  npm_install_at "$prefix" local "@nine-at-a-time-media/ast-mcp@latest" || return 1
  if [ ! -x "$bin" ]; then
    note "project-scope npm install reported success but $bin is missing -- skipping project pre-install"
    return 1
  fi
  note "pre-installed ast-mcp at project scope ($bin) so the committed .mcp.json entry resolves at first connect"
}

# --- Flow functions ---

# provision_via_clai -- delegate to the sibling provision.sh (clai + skills)
# so env-setup fully provisions (#84), not just ast-mcp. Fail-open: a
# provisioning problem must not fail the setup step. provision.sh itself
# execs `clai provision`, so run it as a child (not exec) to return here.
provision_via_clai() {
  local here core
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)" || return 0
  core="$here/../provision.sh"
  if [ ! -f "$core" ] && [ -n "${CLAUDE_PROJECT_DIR:-}" ]; then
    core="$CLAUDE_PROJECT_DIR/sandbox/provision.sh"
  fi
  if [ ! -f "$core" ]; then
    note "sandbox/provision.sh not found next to this script or under \$CLAUDE_PROJECT_DIR -- skipping clai provisioning (ast-mcp already handled above)"
    return 0
  fi
  note "delegating to $core for clai + skills provisioning"
  bash "$core" "$@" || note "provision.sh failed (non-fatal)"
}

setup_flow() {
  # 1) USER scope: the race-winning, cross-repo registration. This is the
  #    core #99 fix -- do it first and independently of clai.
  local user_bin=""
  if user_bin="$(install_ast_mcp_user)"; then
    register_user_scope "$user_bin" || note "ast-mcp installed at user scope but registration in ~/.claude.json failed (non-fatal)"
  else
    note "user-scope ast-mcp install failed -- ast-mcp may connect late this environment (need npm + GH_AI_TOOLS_PAT with read:packages + egress to npm.pkg.github.com and registry.npmjs.org)."
  fi

  # 2) PROJECT scope fallback: pre-install the project-local .ast-mcp the
  #    committed .mcp.json points at, so it resolves at first connect instead
  #    of shadowing the user-scope server with a not-yet-installed binary.
  local project_dir=""
  if project_dir="$(resolve_project_dir)"; then
    install_ast_mcp_project "$project_dir" || note "project-scope pre-install skipped (user scope still carries first connect)"
  else
    note "no committed .mcp.json reachable at setup time -- user scope carries first connect; the SessionStart hook backfills project scope"
  fi

  # 3) Full provisioning (clai + skills) so the environment comes up fully
  #    provisioned, no manual steps (#84).
  provision_via_clai "$@"

  # Env-setup must always succeed: every step above is fail-open.
  exit 0
}

# --- Main ---

main() {
  # No flags of our own: any args pass through to `clai provision` via
  # provision.sh (e.g. none for setup; --offline-ok would come from a
  # maintenance wrapper, not this one).
  setup_flow "$@"
}

main "$@"
