#!/usr/bin/env bash
# smoketest_tds_dist.sh -- behavioral smoke test for lib/tds-dist.sh (the
# non-eval KEY=VALUE parser shared by .pkg and .manifest files) and the
# packages/*.pkg registry (exclusive path ownership, field integrity).
#
# Hermetic: fixtures are throwaway temp files; the registry checks run
# read-only against the real packages/ tree.
#
# Usage: ./test/smoketest_tds_dist.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "${SCRIPT_DIR}")"
LIB="${REPO_DIR}/lib/tds-dist.sh"

# --- Test harness ---

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
WORKROOT=""

red()   { printf '\033[1;31m%s\033[0m' "$1"; }
green() { printf '\033[1;32m%s\033[0m' "$1"; }
bold()  { printf '\033[1m%s\033[0m'    "$1"; }

assert() {
    local label="$1" condition="$2"
    TESTS_RUN=$((TESTS_RUN + 1))
    if eval "${condition}"; then
        green "  PASS"; printf ' %s\n' "${label}"
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        red "  FAIL"; printf ' %s\n' "${label}"
        TESTS_FAILED=$((TESTS_FAILED + 1))
    fi
}

setup()   { WORKROOT="$(mktemp -d "${TMPDIR:-/tmp}/tds-dist-test.XXXXXX")"; }
cleanup() { [ -n "${WORKROOT}" ] && [ -d "${WORKROOT}" ] && rm -rf "${WORKROOT}"; }
trap cleanup EXIT

# --- Fixtures ---

write_fixture() {
    # write_fixture <name> <heredoc on stdin> -> prints path
    local path="${WORKROOT}/$1"
    cat > "${path}"
    printf '%s\n' "${path}"
}

# --- Parser tests ---

test_parser() {
    bold "parser: contract"; printf '\n'

    local good
    good="$(write_fixture good.pkg <<'EOF'
# a comment line
NAME=demo

DESC="quoted value with spaces"
PATHS="a/one b/two"
EMPTY=
EOF
)"
    local out rc=0
    out="$(tds_dist_parse "${good}")" || rc=$?
    assert "good file parses"                 "[ ${rc} -eq 0 ]"
    assert "unquoted value literal"           "grep -q '^NAME=demo\$' <<<\"\${out}\""
    assert "quotes stripped"                  "grep -q '^DESC=quoted value with spaces\$' <<<\"\${out}\""
    assert "list value intact"                "grep -q '^PATHS=a/one b/two\$' <<<\"\${out}\""
    assert "empty value allowed"              "grep -q '^EMPTY=\$' <<<\"\${out}\""
    assert "comments and blanks skipped"      "[ \"\$(wc -l <<<\"\${out}\" | tr -d ' ')\" = 4 ]"

    local canary="${WORKROOT}/canary"
    local evil
    evil="$(write_fixture evil.pkg <<EOF
NAME=\$(touch ${canary})
DESC=\`touch ${canary}\`
PATHS=~/expanded
EOF
)"
    rc=0; out="$(tds_dist_parse "${evil}")" || rc=$?
    assert "substitution-shaped value parses"  "[ ${rc} -eq 0 ]"
    assert "command substitution NOT executed" "[ ! -e '${canary}' ]"
    assert "dollar form stays literal"         "grep -qF 'NAME=\$(touch' <<<\"\${out}\""
    assert "tilde stays literal"               "grep -qF 'PATHS=~/expanded' <<<\"\${out}\""

    bold "parser: rejections"; printf '\n'
    local bad
    bad="$(write_fixture bad-key.pkg <<'EOF'
name=lowercase
EOF
)"
    rc=0; tds_dist_parse "${bad}" >/dev/null 2>&1 || rc=$?
    assert "lowercase key rejected"        "[ ${rc} -ne 0 ]"

    bad="$(write_fixture bad-shape.pkg <<'EOF'
NAME demo
EOF
)"
    rc=0; tds_dist_parse "${bad}" >/dev/null 2>&1 || rc=$?
    assert "line without = rejected"       "[ ${rc} -ne 0 ]"

    # No heredoc here: bash 3.2 cannot parse a heredoc inside $( ) whose
    # body contains an odd number of double quotes (the unbalanced quote
    # under test), so this one fixture is fed to write_fixture via printf.
    bad="$(printf 'NAME="unbalanced\n' | write_fixture bad-quote.pkg)"
    rc=0; tds_dist_parse "${bad}" >/dev/null 2>&1 || rc=$?
    assert "unbalanced quote rejected"     "[ ${rc} -ne 0 ]"

    bad="$(write_fixture bad-dup.pkg <<'EOF'
NAME=one
NAME=two
EOF
)"
    rc=0; tds_dist_parse "${bad}" >/dev/null 2>&1 || rc=$?
    assert "duplicate key rejected"        "[ ${rc} -ne 0 ]"

    rc=0; tds_dist_parse "${WORKROOT}/does-not-exist" >/dev/null 2>&1 || rc=$?
    assert "missing file rejected"         "[ ${rc} -ne 0 ]"
}

test_get() {
    bold "parser: tds_dist_get"; printf '\n'
    local f
    f="$(write_fixture get.pkg <<'EOF'
NAME=demo
DESC="with = sign inside"
EOF
)"
    local rc=0
    assert "get returns value"          "[ \"\$(tds_dist_get '${f}' NAME)\" = demo ]"
    assert "get keeps = in value"       "[ \"\$(tds_dist_get '${f}' DESC)\" = 'with = sign inside' ]"
    tds_dist_get "${f}" ABSENT >/dev/null 2>&1 || rc=$?
    assert "absent key returns nonzero" "[ ${rc} -ne 0 ]"
}

# --- Ownership tests ---

test_ownership() {
    bold "ownership: exclusive path claims"; printf '\n'

    local a b c rc
    a="$(write_fixture own-a.pkg <<'EOF'
NAME=own-a
PATHS="dirone/file bin/tool"
EOF
)"
    b="$(write_fixture own-b.pkg <<'EOF'
NAME=own-b
PATHS="dirtwo"
EOF
)"
    c="$(write_fixture own-c.pkg <<'EOF'
NAME=own-c
PATHS="bin/tool"
EOF
)"
    rc=0; tds_dist_check_ownership "${a}" "${b}" >/dev/null 2>&1 || rc=$?
    assert "disjoint claims pass"       "[ ${rc} -eq 0 ]"
    rc=0; tds_dist_check_ownership "${a}" "${b}" "${c}" >/dev/null 2>&1 || rc=$?
    assert "exact duplicate fails"      "[ ${rc} -ne 0 ]"

    c="$(write_fixture own-nest.pkg <<'EOF'
NAME=own-nest
PATHS="dirtwo/nested/file"
EOF
)"
    rc=0; tds_dist_check_ownership "${b}" "${c}" >/dev/null 2>&1 || rc=$?
    assert "nested-under-claimed-dir fails" "[ ${rc} -ne 0 ]"
}

# --- Registry tests (real packages/) ---

test_registry() {
    bold "registry: packages/*.pkg"; printf '\n'

    local pkgs=("${REPO_DIR}"/packages/*.pkg)
    assert "registry has 13 packages" "[ \${#pkgs[@]} -eq 13 ]"

    local pkg name stem rc all_ok=0 name_ok=0 paths_ok=0 links_ok=0 verify_ok=0
    for pkg in "${pkgs[@]}"; do
        rc=0; tds_dist_parse "${pkg}" >/dev/null 2>&1 || rc=$?
        [ ${rc} -ne 0 ] && { all_ok=1; echo "    parse failed: ${pkg}"; }

        name="$(tds_dist_get "${pkg}" NAME 2>/dev/null || true)"
        stem="$(basename "${pkg}" .pkg)"
        [ "${name}" = "${stem}" ] || { name_ok=1; echo "    NAME!=${stem}: ${pkg}"; }

        local p
        for p in $(tds_dist_get "${pkg}" PATHS 2>/dev/null || true); do
            [ -e "${REPO_DIR}/${p}" ] || { paths_ok=1; echo "    missing path ${p}: ${pkg}"; }
        done

        local pair src
        for pair in $(tds_dist_get "${pkg}" LINKS 2>/dev/null || true); do
            src="${pair#*:}"
            tds_dist_path_claimed "${src}" "${pkg}" \
                || { links_ok=1; echo "    LINK source outside PATHS ${src}: ${pkg}"; }
        done

        local v
        v="$(tds_dist_get "${pkg}" VERIFY 2>/dev/null || true)"
        [ -z "${v}" ] || [ -e "${REPO_DIR}/${v}" ] \
            || { verify_ok=1; echo "    missing VERIFY ${v}: ${pkg}"; }
    done
    assert "all packages parse"              "[ ${all_ok} -eq 0 ]"
    assert "NAME matches filename"           "[ ${name_ok} -eq 0 ]"
    assert "all PATHS exist in repo"         "[ ${paths_ok} -eq 0 ]"
    assert "LINK sources inside own PATHS"   "[ ${links_ok} -eq 0 ]"
    assert "VERIFY scripts exist"            "[ ${verify_ok} -eq 0 ]"

    rc=0; tds_dist_check_ownership "${pkgs[@]}" >/dev/null || rc=$?
    assert "registry ownership exclusive"    "[ ${rc} -eq 0 ]"
}

# --- Flow ---

run_all() {
    setup
    # shellcheck source=../lib/tds-dist.sh
    source "${LIB}"
    test_parser
    test_get
    test_ownership
    test_registry
    printf '\n'
    bold "results: ${TESTS_PASSED}/${TESTS_RUN} passed"
    printf '\n'
    [ "${TESTS_FAILED}" -eq 0 ]
}

# --- Main ---

main() { run_all; }
main "$@"
