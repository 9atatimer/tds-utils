#!/usr/bin/env bash
# provision.sh -- shared core for every provider sandbox wrapper: bootstrap a
# PINNED clai (fetch wheel, verify sha256, install), then exec
# `clai provision` (docs/design/PROVISION.DESIGN.md, issue #84).
#
# Called by the thin per-provider wrappers in sandbox/*/ -- they add nothing
# but provider-appropriate args (e.g. --offline-ok on cached resumes). All
# args are passed through to `clai provision`.
#
# Supply-chain stance (same as .claude/hooks/session-start.sh, the ast-mcp
# precedent this generalizes):
#   - The clai wheel is fetched at the pinned release tag
#     clai-v${CLAI_VERSION} and verified against CLAI_SHA256 from
#     sandbox/pins.env BEFORE install. Checksum failure is fail-CLOSED for
#     the artifact: refuse to install, remove the partial download.
#   - Never curl-pipe-sh. Software lands only via verified release
#     artifacts.
#   - Rolling out new behavior = bumping pins.env (the review gate); this
#     script is deliberately low-velocity.
#
# Session stance: fail-OPEN. Every terminal state exits 0 (see the design
# doc's State Machine) -- a broken release, missing token, missing pins, or
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

# sha256_of <file> -- portable sha256 (Linux sha256sum / macOS shasum).
sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    return 1
  fi
}

# load_pins -- source (and export) sandbox/pins.env, resolved as a sibling
# of this script via BASH_SOURCE so wrappers can call it from anywhere.
# Exported so clai provision inherits TEMPLATE_TOOLS_REPO/AI_TOOLS_REPO;
# the CLAI_* pins are consumed by this script itself.
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

# pins_set -- both executable-artifact pins carry real values. (Session
# hook scripts ship INSIDE the pinned clai wheel via `clai hooks install`,
# so CLAI_VERSION/CLAI_SHA256 are the only pins.)
pins_set() {
  [ "${CLAI_VERSION:-UNSET}" != "UNSET" ] \
    && [ "${CLAI_SHA256:-UNSET}" != "UNSET" ]
}

# warn_pins_unset -- the loud-but-open path for UNSET pins. Says exactly
# what to do to restore them.
warn_pins_unset() {
  note "sandbox/pins.env has UNSET pins -- provisioning is disarmed."
  note "To (re)activate provisioning:"
  note "  1. Pick a clai release with the provision verbs (clai-v0.5.0 or later) in ${AI_TOOLS_REPO:-9atatimer/ai-tools}; set CLAI_VERSION to its version and CLAI_SHA256 to its wheel asset's sha256 (the release API reports it as the asset digest)."
  note "  2. Land the pin values via PR -- the pin bump IS the review gate."
  note "Session continues WITHOUT provisioning (fail-open)."
}

# fetch_wheel -- download the clai wheel for the pinned release tag into
# $TMP. Prefer gh if present; fall back to the REST API with
# GH_AI_TOOLS_PAT (Contents:read on the private repo) -- the exact auth
# chain proven in .claude/hooks/session-start.sh. The GH_TOKEN injected in
# Claude Code web sandboxes is a brokered GitHub-App token that 401s
# against api.github.com directly, hence the dedicated PAT name.
fetch_wheel() {
  local tag="clai-v${CLAI_VERSION}"
  if command -v gh >/dev/null 2>&1; then
    rm -f "$TMP"/*.whl 2>/dev/null
    if gh release download "$tag" --repo "$AI_TOOLS_REPO" \
         --pattern '*.whl' --dir "$TMP" 2>/dev/null \
       && ls "$TMP"/*.whl >/dev/null 2>&1; then
      note "downloaded $tag wheel via gh"
      return 0
    fi
    rm -f "$TMP"/*.whl 2>/dev/null
  fi
  local token="${GH_AI_TOOLS_PAT:-}"
  [ -n "$token" ] || return 1
  command -v python3 >/dev/null 2>&1 || { note "python3 required to parse the release listing"; return 1; }
  local api asset url name
  api="$(curl -fsSL -H "Authorization: Bearer $token" \
         "https://api.github.com/repos/$AI_TOOLS_REPO/releases/tags/$tag" 2>/dev/null)" || return 1
  # First .whl asset: "<api asset url> <asset name>" on one line.
  asset="$(printf '%s' "$api" | python3 -c '
import json, sys
rel = json.load(sys.stdin)
for a in rel.get("assets", []):
    if a.get("name", "").endswith(".whl"):
        print(a["url"], a["name"])
        break
' 2>/dev/null)" || return 1
  [ -n "$asset" ] || return 1
  url="${asset%% *}"
  name="${asset#* }"
  curl -fsSL -H "Authorization: Bearer $token" -H "Accept: application/octet-stream" \
       "$url" -o "$TMP/$name" 2>/dev/null \
    && { note "downloaded $tag wheel via REST API"; return 0; }
  rm -f "$TMP/$name" 2>/dev/null
  return 1
}

# resolve_wheel -- print the path of exactly one downloaded wheel, or fail.
# Installing via a glob when more than one landed could silently install a
# DIFFERENT file than the one verified. Fail closed rather than guess
# (same reasoning as resolve_tarball in the ast-mcp hook).
resolve_wheel() {
  local matches=() f
  for f in "$TMP"/*.whl; do
    [ -e "$f" ] && matches+=("$f")
  done
  case "${#matches[@]}" in
    1) printf '%s\n' "${matches[0]}" ;;
    0) note "no wheel downloaded"; return 1 ;;
    *) note "expected exactly one wheel, found ${#matches[@]}; refusing to guess which to install"; return 1 ;;
  esac
}

# verify_wheel <whl> -- refuse to install unless the wheel hashes to the
# CLAI_SHA256 pin. A missing sha256 tool or a mismatch are both failure
# (fail closed per artifact); the partial/bad download is removed so
# nothing downstream can pick it up.
verify_wheel() {
  local whl="$1" actual
  actual="$(sha256_of "$whl")" || { note "no sha256sum/shasum on PATH; cannot verify, refusing to install"; rm -f "$whl"; return 1; }
  if [ "$actual" != "$CLAI_SHA256" ]; then
    note "CHECKSUM MISMATCH: expected $CLAI_SHA256, got $actual -- refusing to install, removing artifact"
    rm -f "$whl"
    return 1
  fi
  note "checksum verified ($actual)"
}

# install_wheel <whl> -- uv tool install when uv is present (matches how
# clai is installed on the laptop), else pip --user. Both land the `clai`
# entry point in ~/.local/bin.
install_wheel() {
  local whl="$1"
  if command -v uv >/dev/null 2>&1; then
    # --force: reinstalling over an existing (stale or broken) tool
    # environment must succeed -- this is the pin-bump upgrade path.
    uv tool install --force "$whl" >/dev/null 2>&1 || { note "uv tool install failed"; return 1; }
  elif command -v python3 >/dev/null 2>&1; then
    python3 -m pip install --user "$whl" >/dev/null 2>&1 || { note "pip install --user failed"; return 1; }
  else
    note "neither uv nor python3 on PATH; cannot install clai"
    return 1
  fi
  hash -r
  # Fresh sandboxes often lack ~/.local/bin on PATH; both installers put
  # the entry point there.
  if ! command -v clai >/dev/null 2>&1 && [ -x "$HOME/.local/bin/clai" ]; then
    export PATH="$HOME/.local/bin:$PATH"
  fi
  command -v clai >/dev/null 2>&1 || { note "install reported success but clai is not on PATH -- treating as failed install"; return 1; }
  note "installed pinned clai $CLAI_VERSION"
}

# --- Flow functions ---

# bootstrap_clai -- fetch + resolve + verify + install the SAME wheel path
# throughout (no re-globbing between verify and install).
bootstrap_clai() {
  local whl
  fetch_wheel || return 1
  whl="$(resolve_wheel)" || return 1
  verify_wheel "$whl" || return 1
  install_wheel "$whl" || return 1
}

# run_provision -- hand off to clai. Cleans up $TMP first: exec replaces
# the process, so the EXIT trap would never fire. Always passes --copy:
# this script only ever runs inside ephemeral provider sandboxes (Codex,
# Claude web, Copilot, Jules), where symlinks into the clai cache would
# point at a directory the container discards; local laptops reach clai
# provision via clai.d pre-hooks / SessionStart instead, never this script.
run_provision() {
  [ -n "${TMP:-}" ] && rm -rf "$TMP"
  trap - EXIT
  exec clai provision --copy "$@"
}

provision_flow() {
  if ! load_pins; then
    note "cannot load sandbox/pins.env -- skipping provisioning (fail-open)"
    exit 0
  fi

  if ! pins_set; then
    # Pre-rollout: no pin to compare against, so a healthy clai (laptop)
    # goes straight to the idempotent engine, unchanged.
    if clai_healthy; then
      run_provision "$@"
    fi
    warn_pins_unset
    exit 0
  fi

  # True fast path (laptop, warm sandbox resume): only when the installed
  # clai MATCHES the pin. Trusting any healthy clai here would let a warm
  # container keep serving a stale binary forever after a pin bump -- the
  # exact stale-cached-binary failure mode ai-tools issue #72 rejected;
  # the pin bump must take effect on every networked session.
  if clai_healthy && [ "$(installed_clai_version)" = "$CLAI_VERSION" ]; then
    run_provision "$@"
  fi
  if clai_healthy; then
    note "installed clai $(installed_clai_version) != pinned $CLAI_VERSION -- re-bootstrapping to the pin"
  fi

  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT

  if ! bootstrap_clai; then
    if clai_healthy; then
      # DEGRADED, not fatal: a healthy-but-stale clai still provisions this
      # session (offline cached resume, Goal 4) -- with an honest warning
      # that the pin bump has NOT taken effect yet.
      note "WARNING: could not re-bootstrap to pinned clai $CLAI_VERSION; proceeding with STALE installed clai $(installed_clai_version) (honest degradation, Goal 4)"
      run_provision "$@"
    fi
    # BOOTSTRAP FAILED terminal state: log, exit 0, session starts without
    # provisioning (design doc State Machine).
    note "could not fetch+verify+install the pinned clai wheel (need gh, or GH_AI_TOOLS_PAT with Contents:read on $AI_TOOLS_REPO, plus egress to api.github.com and *.githubusercontent.com). Provisioning unavailable this session."
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
