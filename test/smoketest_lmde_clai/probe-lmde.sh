#!/usr/bin/env bash
# probe-lmde.sh -- "did the world get acquired?"
#
# The LMDE half of the story: the agent-agnostic on-disk artifacts that must
# be present before any agent can be configured. On a laptop these are placed
# by `lmde acquire`; in the cloud by `@nine-at-a-time-media/sandbox`. This
# probe is black-box: it only checks the observable end-state, which is the
# same in both environments (with the global CLAUDE.md being cloud-only by
# design -- setup-core.sh skips it on a laptop).
#
# Prerequisites: run from inside the target session (bash probe-lmde.sh); reads
# only, never mutates. No -e: every check must run so the summary is complete.
#
# Usage:  bash probe-lmde.sh
set -uo pipefail

# --- shared libraries ---
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "${HERE}/lib.sh"

# --- helper checks ---

# L1 -- clai launcher is on PATH and runnable.
check_clai_on_path() {
  if command -v clai >/dev/null 2>&1 && clai -V >/dev/null 2>&1; then
    pass L1 "clai-on-path ($(clai -V 2>/dev/null | head -n 1))"
  else
    fail L1 "clai-on-path" "clai not resolvable on PATH or 'clai -V' failed"
  fi
}

# L2 -- ast-mcp binary present at the convention path and executable.
check_ast_mcp_binary() {
  local bin_dir="$1" astmcp target
  astmcp="${bin_dir}/ast-mcp"
  # -e and -x follow symlinks, so this already rejects a dangling/broken link
  # or a non-executable target -- no need for the non-portable `readlink -f`
  # (unavailable on stock BSD/macOS).
  if [ ! -e "${astmcp}" ] || [ ! -x "${astmcp}" ]; then
    fail L2 "ast-mcp-binary" "${astmcp} missing, dangling, or not executable"
    return 0
  fi
  target="$(readlink "${astmcp}" 2>/dev/null || true)"  # single hop, portable, informational
  if [ -n "${target}" ]; then
    pass L2 "ast-mcp-binary (${astmcp} -> ${target})"
  else
    pass L2 "ast-mcp-binary (${astmcp})"
  fi
}

# L3 -- global CLAUDE.md (Claude Code's global instruction file). CLOUD-ONLY:
# placed by naatm-sandbox at /etc/claude-code/CLAUDE.md (override
# CLAUDE_GLOBAL_ETC_DIR, fallback $HOME/CLAUDE.md). On a laptop it is
# deliberately NOT placed, so we skip.
check_global_claude_md() {
  local etc_dir primary fallback found cand
  if ! is_cloud; then
    skip L3 "global-claude-md" "laptop -- placed cloud-only by design"
    return 0
  fi
  etc_dir="${CLAUDE_GLOBAL_ETC_DIR:-/etc/claude-code}"
  primary="${etc_dir}/CLAUDE.md"
  fallback="${HOME}/CLAUDE.md"
  found=""
  for cand in "${primary}" "${fallback}"; do
    [ -f "${cand}" ] && { found="${cand}"; break; }
  done
  if [ -z "${found}" ]; then
    fail L3 "global-claude-md" "no CLAUDE.md at ${primary} or ${fallback}"
  elif grep -qF "Specificity is a virtue" "${found}" 2>/dev/null; then
    pass L3 "global-claude-md (${found}, marker present)"
  else
    fail L3 "global-claude-md" "${found} exists but is missing the known marker"
  fi
}

# L4 -- ~/.local/bin is on PATH. Acquire refuses to edit shell rc and only
# warns; if it is missing, clai/ast-mcp would not resolve for the agent.
check_localbin_on_path() {
  local bin_dir="$1"
  case ":${PATH}:" in
    *":${bin_dir}:"*) pass L4 "localbin-on-path (${bin_dir})" ;;
    *) fail L4 "localbin-on-path" "${bin_dir} is not on PATH" ;;
  esac
}

# --- main ---
main() {
  local bin_dir="${HOME}/.local/bin"
  check_clai_on_path
  check_ast_mcp_binary "${bin_dir}"
  check_global_claude_md
  check_localbin_on_path "${bin_dir}"
  summarize probe-lmde
}

main "$@"
