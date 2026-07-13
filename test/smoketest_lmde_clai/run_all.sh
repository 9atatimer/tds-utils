#!/usr/bin/env bash
# run_all.sh -- canonical entrypoint for the LMDE/CLAI behavioral smoketest,
# matching the per-suite convention (test/smoketest_<name>/run_all.sh).
#
# UNLIKE the hermetic suites (smoketest_lmde_acquire, smoketest_clai_ast_mcp,
# ...), this one is a LIVE, non-hermetic check: it launches a real headless
# `clai claude` session against the deployed toolchain, so it needs clai +
# claude on PATH and costs a little quota (~30-60s). It is a manual/on-demand
# smoketest, not a CI unit gate -- closer in spirit to smoketest_lmde_observability.
#
# This is the laptop half. The cloud half runs as the claude.ai "LMDE/CLAI
# Smoketest" routine (see README.md).
#
# Usage:  test/smoketest_lmde_clai/run_all.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- main ---
main() {
  exec "${HERE}/run-laptop.sh" "$@"
}

main "$@"
