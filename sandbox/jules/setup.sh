#!/usr/bin/env bash
# setup.sh -- Jules environment setup script wrapper: full clai bootstrap +
# provision.
#
# Provider hook contract (Google Jules):
#   The per-repo "environment setup script" runs in the VM before the
#   agent starts, in the repo checkout, with network ON. There is no
#   separate cached-resume hook surface, so this is the single (full
#   bootstrap) entry point. The GH_AI_TOOLS_PAT secret must be configured
#   in the Jules environment for the private-repo fetches.
#
# Install location (manual, by the human -- design non-goal to automate):
#   Jules -> repo Configuration -> Initial setup / environment setup
#   script: paste `bash sandbox/jules/setup.sh` so it runs from the repo
#   checkout, next to sandbox/provision.sh.
#
# Fail-open: provisioning problems never block the VM setup.
set -uo pipefail

# --- Flow functions ---

run_wrapper() {
  local here core
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
  core="$here/../provision.sh"
  if [ ! -f "$core" ]; then
    echo "[sandbox/jules/setup.sh] $core not found -- skipping provisioning (fail-open)" >&2
    exit 0
  fi
  # --copy: Jules VMs are ephemeral -- skills etc. must be COPIES, not
  # symlinks into ~/.cache/clai (design doc: "Ephemeral sandboxes:
  # copies"). Jules does not set CLAUDE_CODE_REMOTE, so pass it explicitly.
  bash "$core" "$@" || echo "[sandbox/jules/setup.sh] provision.sh failed (non-fatal)" >&2
  exit 0
}

# --- Main ---

main() {
  run_wrapper "$@"
}

main "$@"
