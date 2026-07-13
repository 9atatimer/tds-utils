#!/usr/bin/env bash
# probe-clai.sh -- "does the agent see the configuration?"
#
# The CLAI half of the story: the agent-aware wiring `clai` is responsible for.
# Some of it is file-observable in both environments (the emitted MCP config,
# the placed skills). Some of it only exists inside a process that clai itself
# launched (`clai claude` injects telemetry env and runs the cloudflare-disable
# pre-hook). In the cloud the provider launches the agent directly -- there is
# no `clai claude` wrapper (boundary Non-Goal G1) -- so those launch-time cells
# are asserted only on a laptop and treated as expected-absent in the cloud.
#
# Prerequisites: run from inside the target session (bash probe-clai.sh); reads
# only, never mutates. No -e: every check must run so the summary is complete.
#
# Usage:  bash probe-clai.sh
set -uo pipefail

# --- shared libraries ---
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "${HERE}/lib.sh"

# --- helper checks ---

# C1 -- ast-mcp is in the MCP server list the agent reads. clai emits the
# project-scope claude config as <repo>/.mcp.json, keeping the ${HOME} literal
# (placeholder allowlist is HOME-only, and claude expands it at read time).
check_ast_mcp_in_mcp_list() {
  local root="$1" mcp_json cmd
  mcp_json="${root}/.mcp.json"
  if ! have_jq; then
    skip C1 "ast-mcp-in-mcp-list" "jq unavailable"
    return 0
  fi
  if [ ! -f "${mcp_json}" ]; then
    fail C1 "ast-mcp-in-mcp-list" "no ${mcp_json}"
    return 0
  fi
  cmd="$(jq -r '.mcpServers["ast-mcp"].command // empty' "${mcp_json}" 2>/dev/null)"
  # RD5: the claude project-scope .mcp.json must keep the ${HOME} placeholder
  # LITERAL (claude expands it at read time). A resolved absolute path is a
  # contract regression, so assert the literal form, not just a suffix match.
  case "${cmd}" in
    '${HOME}/.local/bin/ast-mcp')
      pass C1 "ast-mcp-in-mcp-list (${cmd})" ;;
    "")
      fail C1 "ast-mcp-in-mcp-list" "ast-mcp absent from ${mcp_json}" ;;
    *'/.local/bin/ast-mcp')
      fail C1 "ast-mcp-in-mcp-list" \
        "command '${cmd}' resolved the \${HOME} placeholder -- RD5 requires the literal \${HOME}/.local/bin/ast-mcp in project scope" ;;
    *)
      fail C1 "ast-mcp-in-mcp-list" "unexpected command '${cmd}' in ${mcp_json}" ;;
  esac
}

# C2 -- the cloudflare MCP servers are disabled for this project. LAPTOP-ONLY:
# written to ~/.claude.json disabledMcpServers by the `clai claude` pre-hook
# 10-disable-cloudflare-mcp. In the cloud the agent is not launched via clai,
# so the hook never runs.
check_cloudflare_disabled() {
  local root="$1" cc conf expected disabled missing name count
  if is_cloud; then
    skip C2 "cloudflare-mcp-disabled" "cloud -- no clai launch wrapper (G1)"
    return 0
  fi
  if ! have_jq; then
    skip C2 "cloudflare-mcp-disabled" "jq unavailable"
    return 0
  fi
  cc="${HOME}/.claude.json"
  if [ ! -f "${cc}" ]; then
    fail C2 "cloudflare-mcp-disabled" "no ${cc} (was this launched via 'clai claude'?)"
    return 0
  fi
  # Expected names are the hook's OWN allowlist -- assert every server it
  # declares, not just one, so a partial regression is caught. Fall back to the
  # known cloudflare set if the conf is unavailable (e.g. a different repo).
  conf="${root}/clai.d/claude/pre/10-disable-cloudflare-mcp.conf"
  expected="$(grep -vE '^[[:space:]]*(#|$)' "${conf}" 2>/dev/null | tr -d '[:blank:]')"
  if [ -z "${expected}" ]; then
    expected=$'cloudflare-graphql\ncloudflare-casb\ncloudflare-bindings\ncloudflare-audit'
  fi
  disabled="$(jq -r --arg p "${root}" \
    '(.projects[$p].disabledMcpServers // [])[]' "${cc}" 2>/dev/null)"
  missing=""
  while IFS= read -r name; do
    [ -z "${name}" ] && continue
    printf '%s\n' "${disabled}" | grep -qx "${name}" || missing="${missing} ${name}"
  done <<< "${expected}"
  if [ -z "${missing}" ]; then
    count="$(printf '%s\n' "${expected}" | grep -c .)"
    pass C2 "cloudflare-mcp-disabled (${count} servers disabled for ${root})"
  else
    fail C2 "cloudflare-mcp-disabled" "not disabled for ${root}:${missing}"
  fi
}

# C3 -- clai injects the observability telemetry env into every agent it
# launches. LAPTOP-ONLY: in the cloud the provider launches the agent directly
# with no clai wrapper (boundary Non-Goal G1), so per design this is an
# expected-absent auto-pass there.
#
# We must observe the injection at its SOURCE -- `clai env` execs `env` through
# clai's launcher and prints the exact environment a launched agent receives.
# Reading our own inherited env instead would be unreliable: Claude Code's Bash
# tool does not mirror the parent claude process's OTEL_* vars into child
# shells, so an in-session probe cannot see them that way.
check_telemetry_injection() {
  local tenv
  if is_cloud; then
    pass C3 "telemetry-injection (cloud auto-pass -- no clai launcher, G1)"
    return 0
  fi
  if ! command -v clai >/dev/null 2>&1; then
    fail C3 "telemetry-injection" "clai not on PATH"
    return 0
  fi
  tenv="$(clai env 2>/dev/null || true)"
  if printf '%s\n' "${tenv}" | grep -q 'OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318' \
    && printf '%s\n' "${tenv}" | grep -qE 'OTEL_RESOURCE_ATTRIBUTES=.*repo='; then
    pass C3 "telemetry-injection (clai injects OTEL_* + repo= resource attr)"
  else
    fail C3 "telemetry-injection" \
      "'clai env' did not expose OTLP endpoint + repo= resource attr"
  fi
}

# C4 -- skills are placed into the agent's skills dir. clai provision syncs
# them into <repo>/.claude/skills (symlinks on a laptop, copies in cloud).
check_skills_placed() {
  local root="$1" skills_dir n
  skills_dir="${root}/.claude/skills"
  if [ -d "${skills_dir}" ] && [ -n "$(ls -A "${skills_dir}" 2>/dev/null)" ]; then
    n="$(ls -A "${skills_dir}" 2>/dev/null | wc -l | tr -d ' ')"
    pass C4 "skills-placed (${skills_dir}, ${n} entries)"
  else
    fail C4 "skills-placed" "${skills_dir} missing or empty"
  fi
}

# --- main ---
main() {
  local root
  root="$(repo_root)"
  check_ast_mcp_in_mcp_list "${root}"
  check_cloudflare_disabled "${root}"
  check_telemetry_injection
  check_skills_placed "${root}"
  summarize probe-clai
}

main "$@"
