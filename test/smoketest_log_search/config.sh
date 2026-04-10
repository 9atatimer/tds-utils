#!/bin/zsh
# config.sh — shared environment for log_search smoke tests

SCRIPT_DIR="${0:A:h}"
REPO_DIR="${SCRIPT_DIR:h:h}"
LOG_SEARCH="${REPO_DIR}/bin/log_search"
LOG_INDEXER="${REPO_DIR}/bin/log_index"

# Index lives in a temp dir per test run — no pollution of real index.
# SMOKE_INDEX_DIR must be set by run_all.sh before scenarios run.
if [[ -z "${SMOKE_INDEX_DIR:-}" ]]; then
  print -u2 "error: SMOKE_INDEX_DIR must be set to an isolated temp directory before sourcing config.sh"
  return 1 2>/dev/null || exit 1
fi
export SMOKE_INDEX_DIR

# Real archived logs — skip if unavailable.
export TDS_LOG_DIR="${TDS_LOG_DIR:-${HOME}/.local/share/log-hoarder}"
export ARCHIVED_DIR="${TDS_LOG_DIR}/archived"
