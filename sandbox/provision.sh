#!/usr/bin/env bash
# provision.sh -- shared core for every provider sandbox wrapper: install a
# PINNED clai from GitHub Packages (npm.pkg.github.com), then exec
# `clai provision` (docs/design/PROVISION.DESIGN.md, issue #84).
#
# Called by the thin per-provider wrappers in sandbox/*/ -- they add nothing
# but provider-appropriate args (e.g. --offline-ok on cached resumes). All
# args are passed through to `clai provision`.
#
# Delivery: `npm install @nine-at-a-time-media/clai@${CLAI_VERSION}` from
# GitHub Packages -- the same registry (and mechanism) the ast-mcp
# SessionStart hook uses post-#98. This REPLACED the previous "download the
# clai wheel as a GitHub Release asset over the api.github.com REST API +
# verify a paired .sha256" delivery: in Claude Code web sandboxes the agent
# proxy blocks raw release-asset egress (both api.github.com/.../releases and
# github.com/.../releases/download return synthetic errors regardless of
# token), so a release-asset path CANNOT work there, while the GitHub Packages
# npm registry IS reachable (RD1, issue #101).
#
# Supply-chain stance (RD3):
#   - clai is installed at the PINNED version from sandbox/pins.env; npm
#     verifies every downloaded tarball against the registry-published
#     integrity hash, and a published version on GitHub Packages is
#     immutable. The gate is thus the pinned VERSION (the review gate) plus
#     npm's built-in integrity -- the hand-fetched CLAI_SHA256 wheel digest
#     is retired. The ai-tools #72 stance is intact: a default-branch push
#     still does not grant execution here, because this installs a pinned
#     released version.
#   - Never curl-pipe-sh. clai lands only via the registry.
#   - Rolling out new behavior = bumping pins.env (the review gate); this
#     script is deliberately low-velocity.
#
# Auth: GH_AI_TOOLS_PAT -- a CLASSIC PAT with read:packages (RD2). GitHub
# Packages npm reads require the classic read:packages scope; fine-grained
# PATs have no Packages permission, and the brokered GH_TOKEN injected in
# Claude web sandboxes cannot read Packages either -- hence the dedicated
# token name.
#
# Session stance: fail-OPEN. Every terminal state exits 0 (see the design
# doc's State Machine) -- a broken publish, missing token, missing pins, or
# dead network must never block an agent session from starting; it only
# costs this session its provisioning, with a log line naming why and what
# to do about it.
#
# No -e: deliberately fail-open at the STEP level, not the script level,
# exactly like the ast-mcp hook. Under -e a single unguarded failing
# command would kill the script before the catch-log-exit-0 logic runs.
# Keep new top-level commands guarded; do not add -e as a shortcut.
set -uo pipefail

# --- Action functions ---

note() { echo "[sandbox/provision.sh] $*" >&2; }

# write_npmrc <dir> -- write an ephemeral, authed npmrc scoping
# @nine-at-a-time-media to GitHub Packages. Token from GH_AI_TOOLS_PAT (a
# classic read:packages PAT). Written mode 600 via umask; the caller removes
# it right after the install so the token does not linger. Mirrors
# .claude/hooks/session-start.sh's write_npmrc, including its hardening.
write_npmrc() {
  local dir="$1" token="${GH_AI_TOOLS_PAT:-}"
  if [ -z "$token" ]; then
    note "GH_AI_TOOLS_PAT unset -- need a classic read:packages PAT to install clai from GitHub Packages"
    return 1
  fi
  mkdir -p "$dir" || return 1
  local npmrc="$dir/.npmrc"
  # Refuse to write the token through a symlink or other non-regular file: a
  # stale symlink there could redirect the secret to an unexpected path. And
  # remove any pre-existing REGULAR .npmrc first, because `>` truncates in
  # place but does NOT change an existing file's mode -- the umask below only
  # governs a NEWLY created file, so a leftover mode-0644 .npmrc would keep
  # 0644 and expose the token. Start fresh either way.
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

# load_pins -- source (and export) sandbox/pins.env, resolved as a sibling
# of this script via BASH_SOURCE so wrappers can call it from anywhere.
# Exported so clai provision inherits TEMPLATE_TOOLS_REPO/AI_TOOLS_REPO;
# CLAI_VERSION is consumed by this script itself.
load_pins() {
  local here
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)" || return 1
  [ -f "$here/pins.env" ] || { note "pins.env not found next to this script ($here/pins.env)"; return 1; }
  set -a
  # shellcheck source=pins.env
  . "$here/pins.env" || { set +a; return 1; }
  set +a
}

# clai_healthy -- clai is on PATH and answers --version.
clai_healthy() {
  command -v clai >/dev/null 2>&1 && clai --version >/dev/null 2>&1
}

# installed_clai_version -- version string of the clai on PATH (last
# whitespace-separated field of `clai --version`).
installed_clai_version() {
  clai --version 2>/dev/null | awk '{print $NF}'
}

# pins_set -- the version pin carries a real value. (Session hook scripts
# ship INSIDE the pinned clai package via `clai hooks install`, so
# CLAI_VERSION is the only pin.)
pins_set() {
  [ "${CLAI_VERSION:-UNSET}" != "UNSET" ]
}

# warn_pins_unset -- the loud-but-open path for an UNSET pin. Says exactly
# what to do to restore it.
warn_pins_unset() {
  note "sandbox/pins.env has an UNSET CLAI_VERSION -- provisioning is disarmed."
  note "To (re)activate provisioning:"
  note "  1. Pick a published @nine-at-a-time-media/clai version on GitHub Packages ('npm view @nine-at-a-time-media/clai version --registry=https://npm.pkg.github.com' with a classic read:packages token configured -- the explicit registry is required, else npm hits registry.npmjs.org and fails for this private package); set CLAI_VERSION to it."
  note "  2. Land the pin value via PR -- the pin bump IS the review gate."
  note "Session continues WITHOUT provisioning (fail-open)."
}

# install_clai -- install the pinned @nine-at-a-time-media/clai from GitHub
# Packages into $CLAI_PREFIX (local, not -g) and put its bin on PATH. The
# clai npm package is a wrapper around clai's self-contained shiv .pyz (its
# "bin" points at the pyz), so the install must land in a STABLE dir that
# survives to `exec clai provision` -- hence $CLAI_PREFIX under $HOME, not a
# throwaway mktemp. Fails closed (returns 1) when npm is missing, the
# token/registry is unusable, or the launched bin isn't present afterward.
install_clai() {
  command -v npm >/dev/null 2>&1 || { note "npm not on PATH -- cannot install clai from GitHub Packages"; return 1; }
  # Refuse a symlinked or non-directory CLAI_PREFIX before creating/writing
  # into it: if it were pre-created as a symlink, mkdir -p would follow it and
  # write_npmrc's token could land outside the intended path. Parallels the
  # same-class guard inside write_npmrc.
  if [ -L "$CLAI_PREFIX" ] || { [ -e "$CLAI_PREFIX" ] && [ ! -d "$CLAI_PREFIX" ]; }; then
    note "refusing to use $CLAI_PREFIX: it exists and is a symlink or non-directory"
    return 1
  fi
  mkdir -p "$CLAI_PREFIX" || return 1
  write_npmrc "$CLAI_PREFIX" || return 1

  # --prefix keeps the install local; --userconfig points npm at the authed
  # npmrc (scope registry + token). clai's own deps (if any) are public;
  # only the scoped package comes from Packages. Capture npm's combined
  # output: quiet on success (log discarded), but on FAILURE the real reason
  # (401/403/E404/network) is echoed to the session log so a broken sandbox
  # is debuggable. (npm's own --silent is unusable here: loglevel=silent
  # suppresses errors too. npm redacts _authToken in its output, so the
  # captured log is safe.)
  local rc=0 log="$CLAI_PREFIX/.npm-install.log"
  npm install --prefix "$CLAI_PREFIX" --userconfig "$CLAI_PREFIX/.npmrc" \
      "@nine-at-a-time-media/clai@${CLAI_VERSION}" >"$log" 2>&1 || rc=1

  # Remove the token file immediately, whatever the outcome. If removal fails
  # (readonly FS, perms, immutable flag) the PAT would linger on disk under the
  # STABLE $CLAI_PREFIX -- unacceptable for a script that runs automatically
  # with a secret present. Blank its contents best-effort so the token is not
  # left readable, then FAIL the install (return 1): better to lose this
  # session's provisioning (the caller stays fail-open) than to keep going
  # while a credential lingers.
  rm -f "$CLAI_PREFIX/.npmrc"
  if [ -e "$CLAI_PREFIX/.npmrc" ]; then
    : > "$CLAI_PREFIX/.npmrc" 2>/dev/null
    rm -f "$log"
    note "ERROR: could not remove token file $CLAI_PREFIX/.npmrc -- blanked its contents best-effort; delete it manually. Failing the install so provisioning does not continue with a lingering credential."
    return 1
  fi

  if [ "$rc" -ne 0 ]; then
    note "npm install of @nine-at-a-time-media/clai@${CLAI_VERSION} failed -- clai unavailable this session."
    # Guard the log print: if npm failed so early the >"$log" redirection
    # never created the file, an unguarded sed would emit a misleading
    # "can't read" and bury the real reason.
    if [ -f "$log" ]; then
      note "npm output:"
      sed 's|^|[sandbox/provision.sh]   |' "$log" >&2
    fi
    rm -f "$log"
    return 1
  fi
  rm -f "$log"

  # A "successful" npm install doesn't guarantee the entrypoint exists
  # (malformed package, unexpected layout). Check the npm-installed BIN SHIM
  # (node_modules/.bin/clai) -- the package.json "bin" field is the
  # published, stable contract -- so a bad install fails closed.
  local entry="$CLAI_PREFIX/node_modules/.bin/clai"
  if [ ! -x "$entry" ]; then
    note "npm install reported success but $entry is missing or not executable -- treating as failed install"
    return 1
  fi
  hash -r
  # Fresh sandboxes won't have the local bin dir on PATH; prepend it so the
  # exec below (and clai's own subprocess calls) resolve clai.
  case ":$PATH:" in
    *":$CLAI_PREFIX/node_modules/.bin:"*) ;;
    *) export PATH="$CLAI_PREFIX/node_modules/.bin:$PATH" ;;
  esac
  command -v clai >/dev/null 2>&1 || { note "install landed $entry but clai is not resolving on PATH -- treating as failed install"; return 1; }
  note "installed pinned clai ${CLAI_VERSION} from GitHub Packages into $CLAI_PREFIX (local, not global)"
}

# --- Flow functions ---

# bootstrap_clai -- install the pinned clai from GitHub Packages.
bootstrap_clai() {
  install_clai || return 1
}

# run_provision -- hand off to clai. Always passes --copy: this script only
# ever runs inside ephemeral provider sandboxes (Codex, Claude web, Copilot,
# Jules), where symlinks into the clai cache would point at a directory the
# container discards; local laptops reach clai provision via clai.d
# pre-hooks / SessionStart instead, never this script. exec replaces the
# process, so nothing after it runs.
run_provision() {
  exec clai provision --copy "$@"
}

provision_flow() {
  if ! load_pins; then
    note "cannot load sandbox/pins.env -- skipping provisioning (fail-open)"
    exit 0
  fi

  # Stable, home-relative install prefix for the clai npm package (the shiv
  # .pyz wrapper must survive to `exec clai provision`). Overridable for
  # tests / non-standard homes.
  CLAI_PREFIX="${CLAI_PREFIX:-$HOME/.clai}"

  if ! pins_set; then
    # Pre-rollout: no pin to compare against, so a healthy clai (laptop)
    # goes straight to the idempotent engine, unchanged.
    if clai_healthy; then
      run_provision "$@"
    fi
    warn_pins_unset
    exit 0
  fi

  # True fast path (warm sandbox resume): only when the installed clai
  # MATCHES the pin. Trusting any healthy clai here would let a warm
  # container keep serving a stale binary forever after a pin bump -- the
  # exact stale-cached-binary failure mode ai-tools issue #72 rejected; the
  # pin bump must take effect on every networked session.
  if clai_healthy && [ "$(installed_clai_version)" = "$CLAI_VERSION" ]; then
    run_provision "$@"
  fi
  if clai_healthy; then
    note "installed clai $(installed_clai_version) != pinned $CLAI_VERSION -- re-bootstrapping to the pin"
  fi

  if ! bootstrap_clai; then
    if clai_healthy; then
      # DEGRADED, not fatal: a healthy-but-stale clai still provisions this
      # session (offline cached resume, Goal 4) -- with an honest warning
      # that the pin bump has NOT taken effect yet.
      note "WARNING: could not (re)install pinned clai $CLAI_VERSION from GitHub Packages; proceeding with STALE installed clai $(installed_clai_version) (honest degradation, Goal 4)"
      run_provision "$@"
    fi
    # BOOTSTRAP FAILED terminal state: log, exit 0, session starts without
    # provisioning (design doc State Machine).
    note "could not install the pinned clai from GitHub Packages (need npm + GH_AI_TOOLS_PAT with read:packages + egress to npm.pkg.github.com). Provisioning unavailable this session."
    exit 0
  fi

  run_provision "$@"
}

# --- Main ---

main() {
  # No flags of our own: everything is passed through to `clai provision`
  # (e.g. --offline-ok from the cached-resume wrappers).
  provision_flow "$@"
}

main "$@"
