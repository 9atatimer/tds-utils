#!/usr/bin/env bash
# setup.sh -- Codex cloud SETUP script wrapper: full clai bootstrap + provision.
#
# Provider hook contract (Codex cloud):
#   Runs once at container CREATE time, in the repo checkout, with network
#   ON. This is the only phase guaranteed egress, so the full bootstrap
#   (npm-install the pinned clai from GitHub Packages, RD1) happens here. Secrets configured
#   in the Codex environment (GH_AI_TOOLS_PAT) are available to setup
#   scripts.
#
# Install location (manual, by the human -- design non-goal to automate):
#   Codex web -> Environments -> <env> -> Setup script: paste
#   `bash sandbox/codex/setup.sh` (or this file's body) so it runs from the
#   repo checkout, next to sandbox/provision.sh.
#
# Fail-open: provisioning problems never block the sandbox from starting.
set -uo pipefail

# --- Flow functions ---

run_wrapper() {
  local here core
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
  core="$here/../provision.sh"
  if [ ! -f "$core" ]; then
    echo "[sandbox/codex/setup.sh] $core not found -- skipping provisioning (fail-open)" >&2
    exit 0
  fi
  # --copy: Codex containers are ephemeral -- skills etc. must be COPIES,
  # not symlinks into ~/.cache/clai (design doc: "Ephemeral sandboxes:
  # copies"). Codex does not set CLAUDE_CODE_REMOTE, so pass it explicitly.
  bash "$core" "$@" || echo "[sandbox/codex/setup.sh] provision.sh failed (non-fatal)" >&2
  exit 0
}

# --- Main ---

main() {
  run_wrapper "$@"
}

main "$@"
