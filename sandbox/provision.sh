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
# Exported so clai provision inherits HOOKS_TAG/HOOKS_SHA256 etc.
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

# pins_set -- all four executable-artifact pins carry real values.
pins_set() {
  [ "${CLAI_VERSION:-UNSET}" != "UNSET" ] \
    && [ "${CLAI_SHA256:-UNSET}" != "UNSET" ] \
    && [ "${HOOKS_TAG:-UNSET}" != "UNSET" ] \
    && [ "${HOOKS_SHA256:-UNSET}" != "UNSET" ]
}

# warn_pins_unset -- the loud-but-open path used during rollout, before the
# first provision-capable clai release exists. Says exactly what to do.
warn_pins_unset() {
  note "sandbox/pins.env still has UNSET pins -- expected during the issue #84 rollout."
  note "To activate provisioning:"
  note "  1. Cut the first clai release with the provision verbs (clai-vNEXT) in ${AI_TOOLS_REPO:-9atatimer/ai-tools}, then set CLAI_VERSION and CLAI_SHA256 (sha256 of the released wheel) in sandbox/pins.env."
  note "  2. Tag hooks-v1 in ${TEMPLATE_TOOLS_REPO:-nine-at-a-time-media/template-tools}, then set HOOKS_TAG and HOOKS_SHA256."
  note "  3. Land the pin bump via PR -- the pin bump IS the review gate."
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
    uv tool install "$whl" >/dev/null 2>&1 || { note "uv tool install failed"; return 1; }
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
# the process, so the EXIT trap would never fire.
run_provision() {
  [ -n "${TMP:-}" ] && rm -rf "$TMP"
  trap - EXIT
  exec clai provision "$@"
}

provision_flow() {
  if ! load_pins; then
    note "cannot load sandbox/pins.env -- skipping provisioning (fail-open)"
    exit 0
  fi

  # Already installed and healthy (laptop, warm sandbox resume): straight
  # to the idempotent engine. Double-invocation is a fast no-op.
  if clai_healthy; then
    run_provision "$@"
  fi

  if ! pins_set; then
    warn_pins_unset
    exit 0
  fi

  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT

  if ! bootstrap_clai; then
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
