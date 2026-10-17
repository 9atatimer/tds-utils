#!/usr/bin/env bash
# smoketest_agent_global.sh -- mechanical invariants of clai.d/AGENT.global.md,
# the machine-wide agent instruction file, plus proof that each check can fail.
#
# The semantic invariants (no rule dropped or weakened, the at-a-glance list in
# step with its sections) are ci.magic assertions in clai.d/ci.magic; this
# suite holds only what a script can decide. Hermetic: reads files, no network.
#
# Usage: ./test/smoketest_agent_global.sh [file]   (default: the real file)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "${SCRIPT_DIR}")"
TARGET="${1:-${REPO_DIR}/clai.d/AGENT.global.md}"

TESTS_RUN=0
TESTS_FAILED=0
WORKROOT=""

red()   { printf '\033[1;31m%s\033[0m' "$1"; }
green() { printf '\033[1;32m%s\033[0m' "$1"; }

cleanup() { [ -n "${WORKROOT}" ] && [ -d "${WORKROOT}" ] && rm -rf "${WORKROOT}"; }
trap cleanup EXIT

# --- Action functions ---

# has_non_ascii <file> -- succeeds when any byte is outside 7-bit ASCII.
has_non_ascii() { LC_ALL=C grep -q '[^ -~	]' "$1"; }

# has_numbered_item <file> -- succeeds on a "1." style list line.
has_numbered_item() { grep -Eq '^[[:space:]]*[0-9]+\.[[:space:]]' "$1"; }

# has_glance_list <file> -- succeeds when the at-a-glance section exists and
# holds at least one bullet before the next heading.
has_glance_list() {
    awk '/^## The hard rules, at a glance/ {on=1; next}
         /^## / {on=0}
         on && /^- / {n++}
         END {exit !(n > 0)}' "$1"
}

# starts_with_header_comment <file> -- the release/symlink explainer must stay.
starts_with_header_comment() { head -n 1 "$1" | grep -q '^<!-- AGENT.global.md'; }

# --- Flow functions ---

check() {
    local label="$1"; shift
    TESTS_RUN=$((TESTS_RUN + 1))
    if "$@"; then
        green "  PASS"; printf ' %s\n' "${label}"
    else
        red "  FAIL"; printf ' %s\n' "${label}"
        TESTS_FAILED=$((TESTS_FAILED + 1))
    fi
}
fails() { ! "$@"; }

run_real_file() {
    printf 'real file: %s\n' "${TARGET}"
    check "is ASCII only" fails has_non_ascii "${TARGET}"
    check "has no numbered list items" fails has_numbered_item "${TARGET}"
    check "keeps the at-a-glance list" has_glance_list "${TARGET}"
    check "keeps the header comment" starts_with_header_comment "${TARGET}"
}

run_fixtures() {
    WORKROOT=$(mktemp -d)
    printf 'curly “quote” and an em—dash\n' > "${WORKROOT}/unicode.md"
    printf -- '- a\n1. first\n' > "${WORKROOT}/numbered.md"
    printf '## Other\n- a\n## The hard rules, at a glance\n\n## Next\n- b\n' > "${WORKROOT}/empty-glance.md"
    printf '# no header comment\n' > "${WORKROOT}/no-header.md"
    printf 'fixtures (each check must be able to fail):\n'
    check "flags non-ASCII" has_non_ascii "${WORKROOT}/unicode.md"
    check "flags a numbered item" has_numbered_item "${WORKROOT}/numbered.md"
    check "flags an empty at-a-glance section" fails has_glance_list "${WORKROOT}/empty-glance.md"
    check "flags a missing header comment" fails starts_with_header_comment "${WORKROOT}/no-header.md"
}

main() {
    run_real_file
    run_fixtures
    printf '\n%d run, %d failed\n' "${TESTS_RUN}" "${TESTS_FAILED}"
    [ "${TESTS_FAILED}" -eq 0 ]
}

main
