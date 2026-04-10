#!/bin/zsh
# config.sh — shared environment for log_search smoke tests

SCRIPT_DIR="${0:A:h}"
REPO_DIR="${SCRIPT_DIR:h:h}"
LOG_SEARCH="${REPO_DIR}/bin/log_search"
LOG_INDEXER="${REPO_DIR}/bin/log_index"

# Index lives in a temp dir per test run — no pollution of real index.
# SMOKE_INDEX_DIR is created by run_all.sh and exported; child scripts inherit it.
export SMOKE_INDEX_DIR="${SMOKE_INDEX_DIR:-}"

# Real archived logs — skip if unavailable.
export TDS_LOG_DIR="${TDS_LOG_DIR:-${HOME}/.local/share/log-hoarder}"
export ARCHIVED_DIR="${TDS_LOG_DIR}/archived"
