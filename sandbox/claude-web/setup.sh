#!/usr/bin/env bash
# setup.sh -- Claude Code web ENVIRONMENT SETUP script: runs BEFORE session
# init and ACQUIRES the agent tooling so it is present when the session (and
# the MCP client) first loads. It discovers the checkout and runs
# `bin/lmde acquire` -- which installs @nine-at-a-time-media/clai (onto PATH)
# and @nine-at-a-time-media/ast-mcp (at ~/.local/bin/ast-mcp) from GitHub
# Packages, skills + catalog riding inside the clai wheel's _data. It does NOT
# configure anything (no skill placement, no ~/.claude.json edit, no MCP
# registration): configuration is clai's job and happens at session start via
# `clai provision` (docs/design/PROVISION.DESIGN.md, issues #99/#84/#145).
#
# Why an env-setup script and not the SessionStart hook (RD4, #99): the MCP
# client connects to the servers in .mcp.json / ~/.claude.json CONCURRENTLY
# with the SessionStart hooks. A hook that installs the ast-mcp binary can
# never win that race for the binary it is itself installing -- first spawn
# ENOENTs, no auto-retry, and ast-mcp only connects on a later reconnect
# (observed connecting late in #99). Acquiring here, in the environment setup
# step that runs BEFORE session init, means the binary already exists when MCP
# first connects. The SessionStart hook remains as an idempotent
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
#     ~/.local/bin/ast-mcp and clai installed here ARE on the session's PATH.
#
# WHAT THIS SCRIPT DOES: it runs `lmde acquire` (clai + ast-mcp + the bundled
# skills/catalog that ride inside the clai wheel) BEFORE session init, all via
# GitHub Packages (npm.pkg.github.com). Acquisition -- transport, pins, the
# binary + wheel install -- is `lmde acquire`'s job; this script only
# discovers the checkout and hands off. Configuration (emit dialects, place
# skills, register ast-mcp at agent scope, epilogue) is NOT done here: it is
# clai's job and runs at session start via `clai provision`. That split is why
# the old in-line ast-mcp install + ~/.claude.json registration + provisioning
# deferral are gone from this file -- the install moved into `lmde acquire`
# and the registration into clai (its clai.d/claude/pre/20-enable-ast-mcp hook
# performs it at session start).
#
# Install location (manual, by the human -- design non-goal to automate):
#   Claude Code web -> Environment settings -> Setup script. Paste the SHIM in
#   sandbox/claude-web/setup-shim.sh, not this file. The shim carries the PAT
#   (the only credential), discovers this checkout, and execs THIS script from
#   git -- so the pasted text never drifts when this file changes.
#
#   The PAT must be a CLASSIC token carrying `read:packages` (RD2). Delivery is
#   the GitHub Packages npm registry (RD1); `Contents:read` buys nothing here
#   and raw release-asset egress is proxy-blocked regardless of token. The PAT
#   arrives as GH_AI_TOOLS_PAT in this stage's environment and is passed
#   through, unchanged, to `lmde acquire`, which owns the authed npmrc; this
#   script itself never writes an .npmrc.
#
# Diagnostics: setup-phase stderr is unreachable from inside the session, so
# every line is ALSO written to ~/.ast-mcp-setup.log (mode 600 -- it must never
# capture a credential; see #117). From a session that came up without ast-mcp:
#   cat ~/.ast-mcp-setup.log
#
# Fail-open: every failure logs and exits 0. A broken acquire/network/token
# must not block the environment or session from coming up -- it only costs
# this environment its tooling/provisioning until access is fixed. `lmde
# acquire` is itself fail-open (it degrades to the already-installed binary and
# still returns 0), so a non-zero from it is an unexpected hard error we still
# absorb here.
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

# is_checkout <dir> -- true iff <dir> is a tds-utils checkout. THREE markers,
# not one: an unrelated repo cloned side-by-side must never false-positive, and
# running a different repo's bin/lmde would be worse than doing nothing.
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
    note "discover_checkout: REFUSING to guess among multiple checkouts (running the wrong repo's bin/lmde, or handing it a credential, is worse than doing nothing):"
    printf '%s\n' "$hits" | while IFS= read -r r; do
      [ -n "$r" ] && note "  candidate: $r"
    done
    return 2   # ambiguous, distinct from "none found"
  fi
  return 1
}

# --- Flow functions ---

# setup_flow -- discover the checkout, then hand off to `lmde acquire`. All
# acquisition machinery (npmrc, install prefixes, dangling-bin cleanup,
# fail-closed-on-missing-bin) lives in `lmde acquire`; this stage only finds
# the checkout, passes the PAT through in the environment, and stays fail-open.
setup_flow() {
  init_log

  local root rc=0
  root="$(discover_checkout)" || rc=$?
  case "$rc" in
    0)
      note "checkout discovered at $root"
      ;;
    2)
      # Ambiguous: discover_checkout already named the candidates. Do NOT run
      # lmde acquire from a guessed checkout (running the wrong repo's bin/lmde,
      # or handing it the PAT, is worse than doing nothing).
      note "multiple checkouts found -- NOT running lmde acquire (fail-open)."
      exit 0
      ;;
    *)
      note "no tds-utils checkout discovered from here -- cannot run lmde acquire (expected on a bare environment; the SessionStart hook still runs clai provision in-session if clai is present)."
      exit 0
      ;;
  esac

  # Hand off acquisition. GH_AI_TOOLS_PAT stays in the environment for
  # `lmde acquire`, which owns the authed npmrc; this script never writes one.
  # --pins names sandbox/pins.env so BOTH clai and ast-mcp install at their
  # reviewed pins (an UNSET key in that file floats to latest). `lmde acquire`
  # is fail-open and returns 0 even when it degrades, so a non-zero here is an
  # unexpected hard error -- absorb it and still exit 0.
  bash "$root/bin/lmde" acquire --pins "$root/sandbox/pins.env" \
    || note "lmde acquire failed (non-fatal)"

  # Env-setup must always succeed: every step above is fail-open.
  exit 0
}

# --- Main ---

main() {
  # No flags. This stage discovers the checkout and runs `lmde acquire`;
  # nothing else takes arguments, and nothing is forwarded anywhere.
  setup_flow
}

main "$@"
