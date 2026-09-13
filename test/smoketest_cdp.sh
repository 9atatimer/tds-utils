#!/usr/bin/env bash
# smoketest_cdp.sh -- behavioral smoke test for bin/cdp and bin/realchrome-cdp,
# the bring-up / bring-down commands for a CDP-tethered browser whose profile
# lives in the current repo's .cdp/ sandbox.
#
# Hermetic: no network, no test sleeps, no real browser. Each case builds a
# throwaway git repo and drives the command through its seams:
#   CDP_BRAVE_BIN / CDP_CFT_BIN / CDP_REALCHROME_BIN
#       -- the browser executable; here a stub that records argv and exits.
#   CDP_PROBE -- run as "$CDP_PROBE" PORT; exit 0 means the CDP endpoint on
#       PORT answers. Here a stub whose answer the case controls.
#   CDP_LISTENER_PID -- run as "$CDP_LISTENER_PID" PORT; prints the pid that
#       holds PORT. Here a stub whose answer the case controls.
#
# The facts under test:
#   - the browser is an argument (brave|cft); omitted, it is the repo's last
#     used browser, else brave;
#   - each browser's profile is <repo>/.cdp/<browser>/profile, never shared;
#   - `up` refuses a repo whose .cdp/ is not gitignored (the profile holds
#     live session cookies);
#   - `up` refuses a port held by a process that is not this profile's browser;
#   - `down` stops the recorded process and clears the pid file;
#   - cft launches with --use-mock-keychain: without it Chrome for Testing
#     blocks on the macOS Keychain at shutdown and ignores SIGTERM;
#   - realchrome-cdp is a distinct command with its own profile, and cdp never
#     accepts realchrome as a browser.
#
# Usage: ./test/smoketest_cdp.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "${SCRIPT_DIR}")"
CDP="${REPO_DIR}/bin/cdp"
REALCHROME="${REPO_DIR}/bin/realchrome-cdp"

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
WORKROOT=""

red()   { printf '\033[1;31m%s\033[0m' "$1"; }
green() { printf '\033[1;32m%s\033[0m' "$1"; }
bold()  { printf '\033[1m%s\033[0m'    "$1"; }

assert() {
    local label="$1"
    local condition="$2"
    TESTS_RUN=$((TESTS_RUN + 1))
    if eval "${condition}"; then
        green "  PASS"; printf ' %s\n' "${label}"
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        red "  FAIL"; printf ' %s\n' "${label}"
        TESTS_FAILED=$((TESTS_FAILED + 1))
    fi
}

cleanup() {
    [ -n "${BG_PID:-}" ] && kill "${BG_PID}" 2>/dev/null || true
    [ -n "${WORKROOT}" ] && rm -rf "${WORKROOT}"
}
trap cleanup EXIT

# --- Fixture ---------------------------------------------------------------

WORKROOT="$(mktemp -d)"
STUBDIR="${WORKROOT}/stubs"
ARGV_LOG="${WORKROOT}/argv.log"
PROBE_STATE="${WORKROOT}/probe.state"
LISTENER_STATE="${WORKROOT}/listener.state"
BG_PID=""

make_stubs() {
    mkdir -p "${STUBDIR}"
    local b
    for b in brave cft realchrome; do
        cat > "${STUBDIR}/${b}" <<EOF
#!/usr/bin/env bash
printf '%s' "${b}" >> "${ARGV_LOG}"
printf ' %s' "\$@" >> "${ARGV_LOG}"
printf '\n' >> "${ARGV_LOG}"
EOF
        chmod +x "${STUBDIR}/${b}"
    done
    # probe answers "up" when PROBE_STATE says up.
    cat > "${STUBDIR}/probe" <<EOF
#!/usr/bin/env bash
[ "\$(cat "${PROBE_STATE}" 2>/dev/null)" = up ]
EOF
    cat > "${STUBDIR}/listener" <<EOF
#!/usr/bin/env bash
cat "${LISTENER_STATE}" 2>/dev/null || true
EOF
    chmod +x "${STUBDIR}/probe" "${STUBDIR}/listener"
}

# new_repo [ignored] -- a fresh git repo; .cdp/ gitignored unless "noignore".
new_repo() {
    local repo
    repo="$(cd "$(mktemp -d "${WORKROOT}/repo.XXXXXX")" && pwd -P)"
    git -C "${repo}" init -q
    if [ "${1:-}" != noignore ]; then
        printf '.cdp/\n' > "${repo}/.gitignore"
    fi
    : > "${ARGV_LOG}"
    printf 'up' > "${PROBE_STATE}"
    : > "${LISTENER_STATE}"
    printf '%s' "${repo}"
}

# run <cmd> <repo> args... -- run a command with cwd in repo, seams wired.
# Captures combined output in OUT and exit status in RC.
run() {
    local cmd="$1" repo="$2"
    shift 2
    set +e
    OUT="$(cd "${repo}" && \
        CDP_BRAVE_BIN="${STUBDIR}/brave" \
        CDP_CFT_BIN="${STUBDIR}/cft" \
        CDP_REALCHROME_BIN="${STUBDIR}/realchrome" \
        CDP_PROBE="${STUBDIR}/probe" \
        CDP_LISTENER_PID="${STUBDIR}/listener" \
        "${cmd}" "$@" 2>&1)"
    RC=$?
    set -e
}

# fake_running <repo> <browser> -- pretend that profile's browser is running:
# a disposable background process recorded as its pid and as the port holder.
fake_running() {
    local repo="$1" browser="$2"
    sleep 60 &
    BG_PID=$!
    mkdir -p "${repo}/.cdp/${browser}"
    printf '%s' "${BG_PID}" > "${repo}/.cdp/${browser}/browser.pid"
    printf '9322' > "${repo}/.cdp/${browser}/port"
    printf '%s' "${BG_PID}" > "${LISTENER_STATE}"
}

# --- Cases -----------------------------------------------------------------

case_default_is_brave() {
    bold "up with no argument in a fresh repo launches brave"; echo
    local repo
    repo="$(new_repo)"
    printf 'down' > "${PROBE_STATE}"
    # probe flips to up once the stub has been exec'd: emulate by making the
    # brave stub mark the probe up.
    printf 'printf up > "%s"\n' "${PROBE_STATE}" >> "${STUBDIR}/brave"
    run "${CDP}" "${repo}" up
    assert "exit 0" '[ "${RC}" -eq 0 ]'
    assert "brave stub was launched" 'grep -q "^brave " "${ARGV_LOG}"'
    assert "profile is <repo>/.cdp/brave/profile" \
        'grep -q -- "--user-data-dir=${repo}/.cdp/brave/profile" "${ARGV_LOG}"'
    assert "default port 9322" 'grep -q -- "--remote-debugging-port=9322" "${ARGV_LOG}"'
    assert "brave keeps the real keychain" '! grep -q -- "--use-mock-keychain" "${ARGV_LOG}"'
    assert "last-browser recorded as brave" \
        '[ "$(cat "${repo}/.cdp/last-browser")" = brave ]'
    assert "profile dir created" '[ -d "${repo}/.cdp/brave/profile" ]'
}

case_explicit_cft_and_last_used() {
    bold "up cft records cft; a later bare status/down defaults to cft"; echo
    local repo
    repo="$(new_repo)"
    printf 'down' > "${PROBE_STATE}"
    printf 'printf up > "%s"\n' "${PROBE_STATE}" >> "${STUBDIR}/cft"
    run "${CDP}" "${repo}" up cft --port 9444
    assert "exit 0" '[ "${RC}" -eq 0 ]'
    assert "cft stub was launched" 'grep -q "^cft " "${ARGV_LOG}"'
    assert "profile is <repo>/.cdp/cft/profile" \
        'grep -q -- "--user-data-dir=${repo}/.cdp/cft/profile" "${ARGV_LOG}"'
    assert "--port honored" 'grep -q -- "--remote-debugging-port=9444" "${ARGV_LOG}"'
    assert "cft uses the mock keychain (else it hangs on quit)" \
        'grep "^cft " "${ARGV_LOG}" | grep -q -- "--use-mock-keychain"'
    assert "last-browser is cft" '[ "$(cat "${repo}/.cdp/last-browser")" = cft ]'
    run "${CDP}" "${repo}" status
    assert "bare status reports cft" 'printf "%s" "${OUT}" | grep -q "cft"'
}

case_refuses_unignored_sandbox() {
    bold "up refuses when .cdp/ is not gitignored"; echo
    local repo
    repo="$(new_repo noignore)"
    printf 'down' > "${PROBE_STATE}"
    run "${CDP}" "${repo}" up
    assert "nonzero exit" '[ "${RC}" -ne 0 ]'
    assert "nothing launched" '[ ! -s "${ARGV_LOG}" ]'
    assert "message names .gitignore" 'printf "%s" "${OUT}" | grep -q "gitignore"'
}

case_refuses_foreign_port() {
    bold "up refuses a port held by some other process"; echo
    local repo
    repo="$(new_repo)"
    printf 'up' > "${PROBE_STATE}"
    printf '99999' > "${LISTENER_STATE}"
    run "${CDP}" "${repo}" up
    assert "nonzero exit" '[ "${RC}" -ne 0 ]'
    assert "nothing launched" '[ ! -s "${ARGV_LOG}" ]'
    assert "message names the port" 'printf "%s" "${OUT}" | grep -q "9322"'
}

case_up_is_idempotent() {
    bold "up when this profile's browser already holds the port is a no-op"; echo
    local repo
    repo="$(new_repo)"
    fake_running "${repo}" brave
    run "${CDP}" "${repo}" up brave
    assert "exit 0" '[ "${RC}" -eq 0 ]'
    assert "nothing launched" '[ ! -s "${ARGV_LOG}" ]'
    kill "${BG_PID}" 2>/dev/null || true
    BG_PID=""
}

case_down_stops_process() {
    bold "down stops the recorded browser and clears the pid file"; echo
    local repo pid
    repo="$(new_repo)"
    fake_running "${repo}" brave
    printf 'brave' > "${repo}/.cdp/last-browser"
    pid="${BG_PID}"
    run "${CDP}" "${repo}" down
    wait "${pid}" 2>/dev/null || true
    assert "exit 0" '[ "${RC}" -eq 0 ]'
    assert "process is gone" '! kill -0 "${pid}" 2>/dev/null'
    assert "pid file removed" '[ ! -e "${repo}/.cdp/brave/browser.pid" ]'
    BG_PID=""
}

case_down_when_not_running() {
    bold "down with nothing running is a clean no-op"; echo
    local repo
    repo="$(new_repo)"
    run "${CDP}" "${repo}" down
    assert "exit 0" '[ "${RC}" -eq 0 ]'
    assert "says not running" 'printf "%s" "${OUT}" | grep -q "not running"'
}

case_rejects_unknown_browser() {
    bold "cdp rejects browsers other than brave|cft, including realchrome"; echo
    local repo
    repo="$(new_repo)"
    run "${CDP}" "${repo}" up realchrome
    assert "nonzero exit for realchrome" '[ "${RC}" -ne 0 ]'
    run "${CDP}" "${repo}" up firefox
    assert "nonzero exit for firefox" '[ "${RC}" -ne 0 ]'
    assert "nothing launched" '[ ! -s "${ARGV_LOG}" ]'
}

case_requires_git_repo() {
    bold "cdp refuses to run outside a git repo"; echo
    local dir
    dir="$(mktemp -d "${WORKROOT}/norepo.XXXXXX")"
    : > "${ARGV_LOG}"
    run "${CDP}" "${dir}" up
    assert "nonzero exit" '[ "${RC}" -ne 0 ]'
    assert "nothing launched" '[ ! -s "${ARGV_LOG}" ]'
}

case_realchrome_distinct() {
    bold "realchrome-cdp launches real Chrome on its own profile"; echo
    local repo
    repo="$(new_repo)"
    printf 'down' > "${PROBE_STATE}"
    printf 'printf up > "%s"\n' "${PROBE_STATE}" >> "${STUBDIR}/realchrome"
    run "${REALCHROME}" "${repo}" up
    assert "exit 0" '[ "${RC}" -eq 0 ]'
    assert "realchrome stub was launched" 'grep -q "^realchrome " "${ARGV_LOG}"'
    assert "profile is <repo>/.cdp/realchrome/profile" \
        'grep -q -- "--user-data-dir=${repo}/.cdp/realchrome/profile" "${ARGV_LOG}"'
    assert "does not touch cdp's last-browser" '[ ! -e "${repo}/.cdp/last-browser" ]'
    run "${REALCHROME}" "${repo}" up brave
    assert "rejects a browser argument" '[ "${RC}" -ne 0 ]'
}

# --- Main ------------------------------------------------------------------

main() {
    make_stubs
    case_default_is_brave
    make_stubs
    case_explicit_cft_and_last_used
    make_stubs
    case_refuses_unignored_sandbox
    case_refuses_foreign_port
    case_up_is_idempotent
    case_down_stops_process
    case_down_when_not_running
    case_rejects_unknown_browser
    case_requires_git_repo
    make_stubs
    case_realchrome_distinct

    echo
    printf '%s run, %s passed, %s failed\n' \
        "${TESTS_RUN}" "${TESTS_PASSED}" "${TESTS_FAILED}"
    [ "${TESTS_FAILED}" -eq 0 ]
}

main "$@"
