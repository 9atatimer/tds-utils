#!/usr/bin/env bash
# maintenance.sh -- Codex cloud MAINTENANCE script wrapper: provision with
# --offline-ok for cached container resumes.
#
# Provider hook contract (Codex cloud):
#   Runs when a CACHED container is resumed for a new task. Network may be
#   OFF (Codex environments can disable egress after setup), so this
#   wrapper must tolerate no-egress: `clai provision --offline-ok` uses
#   cached state and warns about exactly what is stale (Goal 4, honest
#   degradation). If clai was never installed (setup.sh never ran with
#   network), the bootstrap fails LOUDLY-but-open and the session starts
#   unprovisioned.
#
# Install location (manual, by the human -- design non-goal to automate):
#   Codex web -> Environments -> <env> -> Maintenance script: paste
#   `bash sandbox/codex/maintenance.sh` so it runs from the repo checkout,
#   next to sandbox/provision.sh.
set -uo pipefail

# --- Flow functions ---

run_wrapper() {
  local here core
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
  core="$here/../provision.sh"
  if [ ! -f "$core" ]; then
    echo "[sandbox/codex/maintenance.sh] $core not found -- skipping provisioning (fail-open)" >&2
    exit 0
  fi
  # --copy: same reason as setup.sh -- ephemeral container, copies not
  # symlinks; Codex does not set CLAUDE_CODE_REMOTE.
  bash "$core" --offline-ok "$@" || echo "[sandbox/codex/maintenance.sh] provision.sh failed (non-fatal)" >&2
  exit 0
}

# --- Main ---

main() {
  run_wrapper "$@"
}

main "$@"
