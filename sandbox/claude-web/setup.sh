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
# LIFECYCLE -- MEASURED, not assumed. Read before changing anything here.
#
# Claude Code web builds a session in this order:
#
#   1. set up cloud container
#   2. CLONE THE REPOSITORY          -> it lands at /home/<user>/<repo>
#   3. RUN THIS SETUP SCRIPT         -> post-checkout, PRE-session-init
#   4. START CLAUDE CODE
#
# So this is the only stage that is both after the checkout and before the MCP
# client exists. Measured facts about it (issue #111):
#
#   * The repo IS here. $CLAUDE_PROJECT_DIR is UNSET, so we must DISCOVER the
#     checkout, never ask for it.
#   * NO GH_*/GITHUB_* environment variables are injected -- only CLAUDE_*.
#     The session gets them; this stage does not. The credential therefore has
#     to arrive in the pasted Setup-script text (see "Install location").
#   * Egress works: npm.pkg.github.com answers 401 unauthenticated and 200 with
#     a classic read:packages PAT; registry.npmjs.org answers 200.
#   * $HOME is continuous with the session ($HOME=/root, uid 0 in both), so a
#     ~/.claude.json written here IS read by the session.
#
# WHY THIS STAGE AT ALL (RD4): the MCP client connects to the servers named in
# .mcp.json CONCURRENTLY with the SessionStart hooks. A hook that installs the
# ast-mcp binary can never win that race for the binary it is itself
# installing; the server ENOENTs on first spawn and only appears on a later
# retry (observed: a ~5 minute lag). Installing here means the binary exists
# before the client ever looks.
#
# WHAT THIS SCRIPT DOES NOT DO -- and why:
#   It does NOT run `clai provision`. clai fetches the canonical skills/ tree
#   and mcp/manifest.json by GIT-CLONING nine-at-a-time-media/template-tools,
#   and the web git proxy brokers ONLY the session's own repo -- so that clone
#   is unreachable here no matter what token we hold. Running it would buy a
#   warm clai binary at the cost of a second npm install (the SessionStart hook
#   does the same work moments later) and the risk of a stalled clone hanging
#   the environment BUILD. Skills provisioning stays with the hook until the
#   data ships as an npm package (template-tools#145); then this script can own
#   the whole job. See issues #116, #120.
#
# Install location (manual, by the human -- design non-goal to automate):
#   Claude Code web -> Environment settings -> Setup script. Paste the SHIM in
#   sandbox/claude-web/setup-shim.sh, not this file. The shim carries the PAT
#   (the only credential), discovers this checkout, and execs THIS script from
#   git -- so the pasted text never drifts when this file changes.
#
#   The PAT must be a CLASSIC token carrying `read:packages` (RD2). Delivery is
#   the GitHub Packages npm registry (RD1); `Contents:read` buys nothing here
#   and raw release-asset egress is proxy-blocked regardless of token.
#
# Diagnostics: setup-phase stderr is unreachable from inside the session, so
# every line is ALSO written to ~/.ast-mcp-setup.log (mode 600 -- it must never
# capture a credential; see #117). From a session that came up without ast-mcp:
#   cat ~/.ast-mcp-setup.log
#
# Registration scope (#99, revised): ONE binary path, registered twice.
#   Install @nine-at-a-time-media/ast-mcp to ~/.local via `npm install -g
#   --prefix`, landing the executable at ~/.local/bin/ast-mcp -- the SAME
#   path clai's clai.d/*/pre/20-enable-ast-mcp hooks register and the SAME
#   path the laptop's install-claude-user.sh writes -- then register it in
#   ~/.claude.json (user scope). The committed <repo>/.mcp.json names the
#   very same binary as "${HOME}/.local/bin/ast-mcp", which Claude Code
#   expands in the spawned server's own environment (RD5).
#
#   Because both scopes now resolve to ONE executable, ast-mcp connects
#   whichever scope wins: project scope shadows user scope by name when the
#   committed .mcp.json entry is approved, and is skipped in favor of user
#   scope when it is not (a fresh clone carries no approval). Previously the
#   project entry pointed at a project-local .ast-mcp/ tree that had to be
#   installed separately -- an extra install, an extra failure mode, and a
#   "Conflicting scopes" diagnostic. That project-local install is gone.
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

# Setup-phase stderr is often unreachable from the session that follows, so
# every note() line is mirrored here. A session with no ast-mcp reads this to
# find out why.
LOG="${HOME}/.ast-mcp-setup.log"

# --- Action functions ---

# note <msg> -- log to stderr AND to $LOG. Deliberately not `tee`: if $LOG is
# unwritable (read-only $HOME, odd sandbox), tee's failure would swallow the
# message on stderr too. Losing the file is acceptable; losing the diagnostic
# is not.
note() {
  local line="[sandbox/claude-web/setup.sh] $*"
  printf '%s\n' "$line" >&2
  printf '%s\n' "$line" >> "$LOG" 2>/dev/null || true
}

# init_log -- start each environment build with a fresh, private log. Mode 600
# because the pasted shim carries a PAT and this file must never become a way
# to read it (#117). Never fatal.
init_log() {
  ( umask 077; : > "$LOG" ) 2>/dev/null || true
  chmod 600 "$LOG" 2>/dev/null || true
  note "start $(date -u '+%Y-%m-%dT%H:%M:%SZ')  HOME=$HOME  cwd=$PWD"
  note "node=$(command -v node || echo MISSING) ($(node -v 2>/dev/null || echo n/a))  npm=$(command -v npm || echo MISSING)"
  note "GH_AI_TOOLS_PAT $([ -n "${GH_AI_TOOLS_PAT:-}" ] && echo SET || echo NOT-SET)"
  # Which GH_*/TOKEN-ish variables reach THIS stage at all. NAMES ONLY -- never
  # values. init_log() hardens $LOG to mode 600, but that chmod is best-effort
  # (a read-only or exotic $HOME makes it a no-op) and these lines also go to
  # stderr, which the environment may capture anywhere. Never log a value.
  # If the environment's variables are injected into the session but not into
  # the setup script, this line is how we find out (it prints an empty list)
  # instead of guessing.
  note "env var names visible here: [$(env | sed -n 's/^\(GH_[A-Za-z0-9_]*\|GITHUB_[A-Za-z0-9_]*\|CLAUDE_[A-Za-z0-9_]*\)=.*/\1/p' | sort | tr '\n' ' ')]"
  note "cwd contents: [$(ls -A . 2>/dev/null | head -12 | tr '\n' ' ')]"
  note "CLAUDE_PROJECT_DIR=[${CLAUDE_PROJECT_DIR:-<unset>}]  whoami=$(id -un 2>/dev/null)"
}

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

# npm_install_at <prefix> <spec> -- run one authed GLOBAL npm install into
# <prefix> (`-g --prefix`, so the bin lands in <prefix>/bin), writing and
# removing the token npmrc around it and surfacing npm's output on failure.
# Returns npm's success/failure; does NOT verify the resulting bin (the
# caller does).
npm_install_at() {
  local prefix="$1" spec="$2" rc=0
  command -v npm >/dev/null 2>&1 || { note "npm not on PATH -- cannot install $spec"; return 1; }
  if [ -L "$prefix" ] || { [ -e "$prefix" ] && [ ! -d "$prefix" ]; }; then
    note "refusing to use $prefix: it exists and is a symlink or non-directory"
    return 1
  fi
  mkdir -p "$prefix" || return 1
  write_npmrc "$prefix" || return 1
  local log="$prefix/.npm-install.log"
  npm install -g --prefix "$prefix" --userconfig "$prefix/.npmrc" \
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

# cleanup_dangling_bin -- issue #113. A partial `npm install -g` can leave
# ~/.local/bin/ast-mcp as a symlink whose target was never written. The
# committed .mcp.json spawns exactly that path, so a broken install is WORSE
# than no install: the MCP client ENOENTs on a dangling link instead of the
# entry simply being absent. Remove it -- but only when it is not a working
# executable.
#
# Guards, because this runs unattended: the path is a fixed literal under
# $HOME; the parent must really be $HOME/.local/bin (not a symlink pointing
# elsewhere); a healthy binary is never touched; a directory is never removed.
cleanup_dangling_bin() {
  [ -n "${HOME:-}" ] || return 0
  local bin="$HOME/.local/bin/ast-mcp" parent expect
  parent="$(cd "$HOME/.local/bin" 2>/dev/null && pwd -P)" || return 0
  expect="$(cd "$HOME/.local" 2>/dev/null && pwd -P)/bin" || return 0
  if [ "$parent" != "$expect" ]; then
    note "cleanup: \$HOME/.local/bin is not a plain directory under \$HOME/.local -- leaving $bin untouched"
    return 0
  fi
  [ -x "$bin" ] && return 0                        # healthy executable: keep
  { [ -L "$bin" ] || [ -e "$bin" ]; } || return 0  # nothing there at all
  if [ -d "$bin" ]; then
    note "cleanup: $bin is a directory -- refusing to remove it"
    return 0
  fi
  rm -f "$bin" && note "cleanup: removed dangling $bin (#113) so .mcp.json cannot spawn a missing binary"
}

# install_ast_mcp_user -- USER-scope install: @nine-at-a-time-media/ast-mcp
# into ~/.local (global npm), yielding the executable at ~/.local/bin/ast-mcp.
# Echoes that bin path on success. Fails closed if the bin is absent after, and
# never leaves a dangling bin behind on any failure path (#113).
install_ast_mcp_user() {
  local prefix="$HOME/.local" bin="$HOME/.local/bin/ast-mcp"
  if ! npm_install_at "$prefix" "@nine-at-a-time-media/ast-mcp@latest"; then
    cleanup_dangling_bin
    return 1
  fi
  if [ ! -x "$bin" ]; then
    note "npm install reported success but $bin is missing or not executable -- treating as failed install"
    cleanup_dangling_bin
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

# is_checkout <dir> -- true iff <dir> is a tds-utils checkout. THREE markers,
# not one: an unrelated repo cloned side-by-side must never false-positive, and
# running a different repo's provision.sh would be worse than doing nothing.
is_checkout() {
  [ -n "${1:-}" ] \
    && [ -f "$1/sandbox/claude-web/setup.sh" ] \
    && [ -f "$1/sandbox/provision.sh" ] \
    && [ -f "$1/.mcp.json" ]
}

# discover_checkout -- print the checkout root, or return 1. NEVER guesses
# (#118). $CLAUDE_PROJECT_DIR is unset during the Claude web setup stage, so
# asking for it is how the old code silently skipped every run.
#
# Order:
#   1. walk up from this script's own directory. The shim execs the on-disk
#      copy, so BASH_SOURCE[0] is already inside the checkout. This is the
#      normal path and needs no scanning at all.
#   2. $CLAUDE_PROJECT_DIR when it validates (Codex, Jules, a laptop session).
#   3. exactly ONE validating candidate among $PWD/*, /home/*/*, $HOME/*.
#      Two or more -> refuse and name them. A sandbox may hold several repos.
discover_checkout() {
  local d c r hits count root
  d="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd -P)" || d=""
  while [ -n "$d" ] && [ "$d" != "/" ]; do
    if is_checkout "$d"; then printf '%s\n' "$d"; return 0; fi
    d="$(dirname "$d")"
  done

  if is_checkout "${CLAUDE_PROJECT_DIR:-}"; then
    # Print and succeed ONLY if the cd works; a bare `return 0` here would
    # hand the caller an empty path when the dir vanished under us.
    root="$(cd "$CLAUDE_PROJECT_DIR" 2>/dev/null && pwd -P)" \
      && { printf '%s\n' "$root"; return 0; }
  fi

  # Scan roots. SETUP_SCAN_ROOTS exists so the smoketests can confine the scan
  # to a fixture dir. Tested with ${VAR+set}, not ${VAR:-default}: an
  # intentionally EMPTY override must mean "scan nothing", and `:-` would
  # silently reinflate it to the real /home/*/*.
  local -a roots
  if [ -n "${SETUP_SCAN_ROOTS+set}" ]; then
    # Deliberately unquoted: word-splits AND glob-expands the override, so a
    # test can pass "<tmp>/clones/*". An empty value yields an empty array,
    # which is the point -- "scan nothing".
    # shellcheck disable=SC2206
    roots=( ${SETUP_SCAN_ROOTS} )
  else
    roots=("$PWD"/* /home/*/* "$HOME"/*)
  fi

  hits=""
  # An unmatched glob expands to the literal pattern; is_checkout rejects it.
  for c in ${roots[@]+"${roots[@]}"}; do
    is_checkout "$c" || continue
    r="$(cd "$c" 2>/dev/null && pwd -P)" || continue
    hits="$hits$r
"
  done
  hits="$(printf '%s' "$hits" | grep . | sort -u)"
  count="$(printf '%s\n' "$hits" | grep -c . )"
  if [ "$count" -eq 1 ]; then printf '%s\n' "$hits"; return 0; fi
  if [ "$count" -gt 1 ]; then
    note "discover_checkout: REFUSING to guess among multiple checkouts (running the wrong repo's provision.sh, or handing it a credential, is worse than doing nothing):"
    printf '%s\n' "$hits" | while IFS= read -r r; do
      [ -n "$r" ] && note "  candidate: $r"
    done
    return 2   # ambiguous, distinct from "none found"
  fi
  return 1
}

# --- Flow functions ---

# report_provisioning_deferral -- say plainly what this stage did NOT do, and
# why, so nobody reads a quiet log as a healthy one. `clai provision` is NOT
# run here: clai git-clones nine-at-a-time-media/template-tools for skills/ and
# mcp/manifest.json, and the web git proxy brokers only the session's own repo,
# so the clone cannot succeed at any stage of a web session. The SessionStart
# hook owns provisioning until that data ships as an npm package.
report_provisioning_deferral() {
  local root rc=0
  root="$(discover_checkout)" || rc=$?
  case "$rc" in
    0) note "checkout discovered at $root" ;;
    2) note "checkout NOT selected: multiple candidates (listed above)" ;;
    *) note "no tds-utils checkout discovered from here (expected on a bare environment; the SessionStart hook provisions in-session)" ;;
  esac
  note "DEFERRED: skills + per-agent MCP configs are NOT provisioned in this stage."
  note "DEFERRED: reason -- clai fetches skills/ and mcp/manifest.json by cloning nine-at-a-time-media/template-tools, which the web git proxy does not broker (only this session's own repo is reachable). No token changes that."
  note "DEFERRED: the SessionStart hook runs clai provision in-session. Once the data ships as an npm package (template-tools#145), this stage can own the whole job (#120)."
}

setup_flow() {
  init_log

  # Install the ONE ast-mcp binary at ~/.local/bin/ast-mcp BEFORE session init
  # (RD4, #99), and register it at user scope. The committed .mcp.json names
  # this same path via ${HOME}, so project and user scope resolve to one
  # executable and ast-mcp connects whichever scope the client picks.
  local user_bin=""
  if user_bin="$(install_ast_mcp_user)"; then
    register_user_scope "$user_bin" || note "ast-mcp installed at user scope but registration in ~/.claude.json failed (non-fatal)"
  else
    note "user-scope ast-mcp install failed -- ast-mcp will connect late or not at all this environment (need npm + a classic read:packages GH_AI_TOOLS_PAT + egress to npm.pkg.github.com and registry.npmjs.org). Any dangling bin has been removed."
  fi

  report_provisioning_deferral

  # Env-setup must always succeed: every step above is fail-open.
  exit 0
}

# --- Main ---

main() {
  # No flags. This stage installs and registers ast-mcp; nothing else takes
  # arguments, and nothing is forwarded anywhere.
  setup_flow
}

main "$@"
