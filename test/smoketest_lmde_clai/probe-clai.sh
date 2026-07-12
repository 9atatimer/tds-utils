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
# Run me from inside the target session:  bash probe-clai.sh
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "${HERE}/lib.sh"

ROOT="$(repo_root)"
HOME_BIN="${HOME}/.local/bin/ast-mcp"

# C1 -- ast-mcp is in the MCP server list the agent reads. clai emits the
# project-scope claude config as <repo>/.mcp.json, keeping the ${HOME} literal
# (placeholder allowlist is HOME-only, and claude expands it at read time).
mcp_json="${ROOT}/.mcp.json"
if ! have_jq; then
  skip C1 "ast-mcp-in-mcp-list" "jq unavailable"
elif [ ! -f "${mcp_json}" ]; then
  fail C1 "ast-mcp-in-mcp-list" "no ${mcp_json}"
else
  cmd="$(jq -r '.mcpServers["ast-mcp"].command // empty' "${mcp_json}" 2>/dev/null)"
  case "${cmd}" in
    *'/.local/bin/ast-mcp') pass C1 "ast-mcp-in-mcp-list (${cmd})" ;;
    "") fail C1 "ast-mcp-in-mcp-list" "ast-mcp absent from ${mcp_json}" ;;
    *)  fail C1 "ast-mcp-in-mcp-list" "unexpected command '${cmd}' in ${mcp_json}" ;;
  esac
fi

# C2 -- the cloudflare MCP servers are disabled for this project. LAPTOP-ONLY:
# written to ~/.claude.json disabledMcpServers by the `clai claude` pre-hook
# 10-disable-cloudflare-mcp. In the cloud the agent is not launched via clai,
# so the hook never runs.
if is_cloud; then
  skip C2 "cloudflare-mcp-disabled" "cloud -- no clai launch wrapper (G1)"
elif ! have_jq; then
  skip C2 "cloudflare-mcp-disabled" "jq unavailable"
else
  cc="${HOME}/.claude.json"
  if [ ! -f "${cc}" ]; then
    fail C2 "cloudflare-mcp-disabled" "no ${cc} (was this launched via 'clai claude'?)"
  else
    disabled="$(jq -r --arg p "${ROOT}" \
      '(.projects[$p].disabledMcpServers // [])[]' "${cc}" 2>/dev/null)"
    if printf '%s\n' "${disabled}" | grep -qx "cloudflare-graphql"; then
      pass C2 "cloudflare-mcp-disabled (project ${ROOT})"
    else
      fail C2 "cloudflare-mcp-disabled" \
        "cloudflare-graphql not in disabledMcpServers for ${ROOT}"
    fi
  fi
fi

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
if is_cloud; then
  pass C3 "telemetry-injection (cloud auto-pass -- no clai launcher, G1)"
elif ! command -v clai >/dev/null 2>&1; then
  fail C3 "telemetry-injection" "clai not on PATH"
else
  tenv="$(clai env 2>/dev/null || true)"
  if printf '%s\n' "${tenv}" | grep -q 'OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318' \
    && printf '%s\n' "${tenv}" | grep -qE 'OTEL_RESOURCE_ATTRIBUTES=.*repo='; then
    pass C3 "telemetry-injection (clai injects OTEL_* + repo= resource attr)"
  else
    fail C3 "telemetry-injection" \
      "'clai env' did not expose OTLP endpoint + repo= resource attr"
  fi
fi

# C4 -- skills are placed into the agent's skills dir. clai provision syncs
# them into <repo>/.claude/skills (symlinks on a laptop, copies in cloud).
skills_dir="${ROOT}/.claude/skills"
if [ -d "${skills_dir}" ] && [ -n "$(ls -A "${skills_dir}" 2>/dev/null)" ]; then
  n="$(ls -A "${skills_dir}" 2>/dev/null | wc -l | tr -d ' ')"
  pass C4 "skills-placed (${skills_dir}, ${n} entries)"
else
  fail C4 "skills-placed" "${skills_dir} missing or empty"
fi

summarize probe-clai
