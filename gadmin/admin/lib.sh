# gadmin/admin/lib.sh — shared helpers for gadmin built-in subcommands.
#
# This file is sourced (not executed). It must work under bash and zsh.
# Subcommands locate it via: source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

# Resolve through symlinks (bin/gadmin -> ../gadmin/gadmin -> admin/)
ADMIN_LIB_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null || echo "${BASH_SOURCE[0]}")")" && pwd)"

ADMIN_LOG_PREFIX="[gadmin]"

# Walk up from $PWD to find the project root. Recognise (in order):
#   1. a gadmin.d/ extensions directory (explicit gadmin marker)
#   2. a package.json (npm projects)
#   3. a .git directory or file (any git repo)
_find_repo_root() {
  local dir="$PWD"
  while [ "$dir" != "/" ]; do
    if [ -d "$dir/gadmin.d" ] || [ -f "$dir/package.json" ] || [ -e "$dir/.git" ]; then
      printf '%s\n' "$dir"
      return 0
    fi
    dir="$(dirname "$dir")"
  done
  return 1
}
ADMIN_REPO_ROOT="$(_find_repo_root 2>/dev/null || echo "$PWD")"

# ANSI color codes for consistent output across admin scripts
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'  # No Color

function admin_log_set_prefix() {
  local prefix="$1"

  if [[ -z "$prefix" ]]; then
    ADMIN_LOG_PREFIX="[gadmin]"
  else
    ADMIN_LOG_PREFIX="$prefix"
  fi
}

function admin_log_info() {
  printf '%s %s\n' "$ADMIN_LOG_PREFIX" "$*"
}

function admin_log_warn() {
  printf '%s %s\n' "$ADMIN_LOG_PREFIX" "$*" >&2
}

function admin_log_error() {
  printf '%s %s\n' "$ADMIN_LOG_PREFIX" "$*" >&2
}

function admin_log_success() {
  printf '%s %b%s%b\n' "$ADMIN_LOG_PREFIX" "$GREEN" "$*" "$NC"
}
