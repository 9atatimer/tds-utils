#!/usr/bin/env bash
# smoketest_shell_env.sh — behavioral smoke test for the macOS zsh startup
# contract (macos/dot.zshenv, dot.zprofile, dot.zshrc). See issue #176.
#
# The contract under test:
#   .zshenv   — tiny, deterministic, side-effect-light environment for GUI and
#               noninteractive/agent-spawned shells. Static PATH only.
#   .zprofile — login-shell PATH repair AFTER macOS /etc/zprofile path_helper,
#               which demotes anything .zshenv prepended below /bin.
#   .zshrc    — interactive conveniences and runtime-manager init.
#
# Isolation: the dotfiles under test are staged into a throwaway ZDOTDIR and
# exercised with `env -i`, so the real ~/.zshenv is never sourced and the
# developer's live shell configuration is never mutated. The system-wide
# /etc/zshenv and /etc/zprofile DO still run — path_helper being in the loop is
# the entire point of the test.
#
# Real shells, real tools, real $HOME: this is a smoke test, not a unit test.
# Checks that depend on a tool this machine does not have SKIP rather than fail.
# Every shell invocation runs under a watchdog; nothing here can hang.
#
# Usage: ./test/smoketest_shell_env.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "${SCRIPT_DIR}")"
MACOS_DIR="${REPO_DIR}/macos"

# Tools a noninteractive agent-spawned shell must be able to find. This is the
# concrete cash value of the .zshenv migration (issue #176 / #169).
REQUIRED_TOOLS=(bash node npm gh uv git-mirror)

SHELL_TIMEOUT=20

# --- Test harness ---

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
TESTS_SKIPPED=0
STAGE=""

# Tool-resolution blocks, captured once per shell shape by run_all.
LOGIN_TOOLS=""
ILOGIN_TOOLS=""
BARE_TOOLS=""

red()    { printf '\033[1;31m%s\033[0m' "$1"; }
green()  { printf '\033[1;32m%s\033[0m' "$1"; }
yellow() { printf '\033[1;33m%s\033[0m' "$1"; }
bold()   { printf '\033[1m%s\033[0m'    "$1"; }

pass() { green "  PASS";  printf ' %s\n' "$1"; TESTS_PASSED=$((TESTS_PASSED + 1)); }
fail() { red   "  FAIL";  printf ' %s\n' "$1"; TESTS_FAILED=$((TESTS_FAILED + 1)); }
skip() { yellow "  SKIP"; printf ' %s (%s)\n' "$1" "$2"; TESTS_SKIPPED=$((TESTS_SKIPPED + 1)); }

assert_eq() {
    local label="$1" expected="$2" actual="$3"
    TESTS_RUN=$((TESTS_RUN + 1))
    if [ "${expected}" = "${actual}" ]; then
        pass "${label}"
    else
        fail "${label}"
        printf '       expected: %s\n' "${expected}"
        printf '       actual:   %s\n' "${actual}"
    fi
}

assert_ok() {
    local label="$1" condition="$2"
    TESTS_RUN=$((TESTS_RUN + 1))
    if eval "${condition}"; then pass "${label}"; else fail "${label}"; fi
}

# --- Action functions ---

# Run a command under a watchdog so a misbehaving shell can never hang the
# suite. TESTING.md: a hanging test is worse than a failing one.
# The watchdog's stdout MUST be redirected away from the caller's. These calls
# are almost all inside $( ), and a command substitution does not return until
# every process holding the pipe has closed it -- so an inherited pipe would
# make each measurement block for the full timeout no matter how fast the shell
# under test actually was, turning a 30-second suite into a 6-minute one.
run_guarded() {
    local secs="$1"; shift
    local pid killer rc=0
    "$@" & pid=$!
    ( sleep "${secs}"; kill -9 "${pid}" 2>/dev/null ) >/dev/null 2>&1 & killer=$!
    wait "${pid}" || rc=$?
    kill -9 "${killer}" 2>/dev/null || true
    wait "${killer}" 2>/dev/null || true
    return "${rc}"
}

# Stage the dotfiles under test into a throwaway ZDOTDIR.
stage_dotfiles() {
    STAGE="$(mktemp -d "${TMPDIR:-/tmp}/shell-env-test.XXXXXX")"
    cp "${MACOS_DIR}/dot.zshenv"   "${STAGE}/.zshenv"
    cp "${MACOS_DIR}/dot.zprofile" "${STAGE}/.zprofile"
    cp "${MACOS_DIR}/dot.zshrc"    "${STAGE}/.zshrc"
}

cleanup() { [ -n "${STAGE}" ] && [ -d "${STAGE}" ] && rm -rf "${STAGE}"; return 0; }
trap cleanup EXIT

# Evaluate a zsh snippet in a staged shell of a given shape, from a pristine
# environment. Extra VAR=VAL pairs may be injected before the shape argument.
#
# TMUX is pinned non-empty because .zshrc execs `tmux new-session` in
# interactive shells that are not already inside tmux — without this the
# interactive checks would hang rather than report.
staged_zsh() {
    local shape="$1" snippet="$2"; shift 2
    run_guarded "${SHELL_TIMEOUT}" \
        env -i HOME="${HOME}" ZDOTDIR="${STAGE}" TERM=dumb TMUX=smoketest "$@" \
        /bin/zsh "${shape}" "${snippet}" </dev/null 2>/dev/null
}

# A staged interactive shell builds zsh's completion dump on first use, which
# is slow and would otherwise be charged to whichever check ran first. Pay it
# once, up front, outside any assertion.
warm_completion_cache() {
    staged_zsh -lic 'true' >/dev/null 2>&1 || true
}

# Resolve every required tool in ONE shell of the given shape. Spawning a login
# shell per tool is what made the first draft of this suite take minutes.
# Emits "<tool> <path>" lines; the path is empty when the tool is not found.
resolve_tools_in() {
    local shape="$1" snippet=""
    local tool
    for tool in "${REQUIRED_TOOLS[@]}"; do
        snippet+="printf '${tool} %s\\n' \"\$(command -v ${tool} 2>/dev/null)\";"
    done
    staged_zsh "${shape}" "${snippet}"
}

# Look up one tool's path from a captured resolve_tools_in block.
tool_path_from() {
    local block="$1" tool="$2"
    printf '%s\n' "${block}" | awk -v t="${tool}" '$1 == t { print $2; exit }'
}

homebrew_prefix() {
    if   [ -x /opt/homebrew/bin/brew ]; then printf '/opt/homebrew'
    elif [ -x /usr/local/bin/brew    ]; then printf '/usr/local'
    fi
}

# --- Flow functions: acceptance checks from issue #176 ---

# #176: `/bin/zsh -lc 'command -v bash'` must resolve Homebrew bash, not /bin/bash.
# macOS /etc/zprofile runs path_helper AFTER .zshenv and demotes any PATH entry
# .zshenv prepended below /bin, so .zprofile must re-assert the ordering.
check_login_shell_resolves_homebrew_bash() {
    local prefix; prefix="$(homebrew_prefix)"
    if [ -z "${prefix}" ] || [ ! -x "${prefix}/bin/bash" ]; then
        TESTS_RUN=$((TESTS_RUN + 1))
        skip "login shell resolves Homebrew bash" "no Homebrew bash installed"
        return
    fi
    assert_eq "login shell (zsh -lc) resolves Homebrew bash, not /bin/bash" \
        "${prefix}/bin/bash" "$(tool_path_from "${LOGIN_TOOLS}" bash)"
    assert_eq "interactive login shell (zsh -lic) resolves Homebrew bash" \
        "${prefix}/bin/bash" "$(tool_path_from "${ILOGIN_TOOLS}" bash)"
}

# #176: `clai claude --version` must not die in a pre-hook because
# `#!/usr/bin/env bash` resolved to Apple Bash 3.2, which lacks `readarray`.
check_login_shell_bash_has_readarray() {
    local probe="${STAGE}/readarray_probe.sh"
    cat > "${probe}" <<'EOF'
#!/usr/bin/env bash
readarray -t lines < <(printf 'a\nb\n')
[ "${#lines[@]}" -eq 2 ]
EOF
    chmod +x "${probe}"
    TESTS_RUN=$((TESTS_RUN + 1))
    if staged_zsh -lc "'${probe}'" >/dev/null 2>&1; then
        pass "login shell: '#!/usr/bin/env bash' script can use readarray"
    else
        fail "login shell: '#!/usr/bin/env bash' script can use readarray"
        printf '       Apple Bash 3.2 won the PATH; this is the clai pre-hook failure.\n'
    fi
}

# #176: a GUI/noninteractive-style shell must still see the tools that
# motivated the .zshenv migration. Asserted as PARITY with the login shell so
# the test tracks the contract, not this machine's particular install set.
check_noninteractive_shell_sees_tools() {
    local tool login_path bare_path
    for tool in "${REQUIRED_TOOLS[@]}"; do
        login_path="$(tool_path_from "${LOGIN_TOOLS}" "${tool}")"
        TESTS_RUN=$((TESTS_RUN + 1))
        if [ -z "${login_path}" ]; then
            skip "noninteractive shell finds ${tool}" "not installed on this host"
            continue
        fi
        bare_path="$(tool_path_from "${BARE_TOOLS}" "${tool}")"
        if [ -n "${bare_path}" ]; then
            pass "noninteractive shell (zsh -c) finds ${tool}"
        else
            fail "noninteractive shell (zsh -c) finds ${tool}"
            printf '       login shell has it at %s; agent-spawned shells do not.\n' "${login_path}"
        fi
    done
}

# #176: .zshenv must not unconditionally clobber user/session state.
check_ssh_auth_sock_preserved() {
    local sentinel="/tmp/smoketest-agent-sentinel.sock"
    assert_eq "SSH_AUTH_SOCK is preserved when already set" \
        "${sentinel}" \
        "$(staged_zsh -c 'printf %s "${SSH_AUTH_SOCK:-}"' SSH_AUTH_SOCK="${sentinel}")"

    TESTS_RUN=$((TESTS_RUN + 1))
    if [ -n "$(staged_zsh -c 'printf %s "${SSH_AUTH_SOCK:-}"')" ]; then
        pass "SSH_AUTH_SOCK is provided when unset (agents reach the SSH agent)"
    else
        fail "SSH_AUTH_SOCK is provided when unset (agents reach the SSH agent)"
    fi
}

# #176: no heavy runtime-manager initialization in .zshenv. Every `zsh -c` an
# agent spawns pays that cost; sourcing nvm.sh alone measures ~450ms.
check_zshenv_has_no_heavy_init() {
    local pattern
    for pattern in 'nvm\.sh' 'pyenv init' 'brew shellenv' 'direnv hook' 'compinit'; do
        TESTS_RUN=$((TESTS_RUN + 1))
        if grep -Eq "${pattern}" "${MACOS_DIR}/dot.zshenv"; then
            fail ".zshenv is free of heavy init: ${pattern}"
        else
            pass ".zshenv is free of heavy init: ${pattern}"
        fi
    done
}

# The startup-cost budget the rule above exists to protect.
check_noninteractive_startup_is_fast() {
    local budget_ms=150 start end elapsed_ms
    TESTS_RUN=$((TESTS_RUN + 1))
    if [ -z "${EPOCHREALTIME:-}" ]; then
        skip "noninteractive startup under ${budget_ms}ms" "bash lacks EPOCHREALTIME"
        return
    fi
    start="${EPOCHREALTIME}"
    staged_zsh -c 'true' >/dev/null 2>&1 || true
    end="${EPOCHREALTIME}"
    elapsed_ms="$(awk -v a="${start}" -v b="${end}" 'BEGIN { printf "%d", (b - a) * 1000 }')"
    if [ "${elapsed_ms}" -lt "${budget_ms}" ]; then
        pass "noninteractive startup under ${budget_ms}ms (${elapsed_ms}ms)"
    else
        fail "noninteractive startup under ${budget_ms}ms (${elapsed_ms}ms)"
    fi
}

# .zshenv resolves nvm's default node bin statically, without paying the ~456ms
# cost of nvm's loader. That resolver is invisible to the parity checks above:
# it degrades by dropping the entry, and Homebrew's node then backfills `node`
# and `npm`, so both shell shapes stay equal and equally wrong. Meanwhile the
# binary that actually vanishes -- `claude`, an npm global scoped to one node
# version -- is not a tool any other check probes. So exercise the resolver
# directly, against the alias shapes nvm really writes.
#
# Cases are driven through a synthetic NVM_DIR: real tree layout, no real nvm.
check_nvm_default_resolution() {
    local fake="${STAGE}/fakenvm" ver="v24.18.0"
    local label alias_content expect on_path
    mkdir -p "${fake}/alias/lts" "${fake}/versions/node/${ver}/bin"
    printf 'lts/krypton\n' > "${fake}/alias/lts/*"
    printf '%s\n' "${ver}"  > "${fake}/alias/lts/krypton"

    # label | contents of alias/default | expect the bin dir on PATH?
    while IFS='|' read -r label alias_content expect; do
        [ -n "${label}" ] || continue
        printf '%b' "${alias_content}" > "${fake}/alias/default"
        on_path="$(staged_zsh -c \
            "print -rl -- \$path | grep -c '^${fake}/versions/node/${ver}/bin\$' || true" \
            NVM_DIR="${fake}")"
        TESTS_RUN=$((TESTS_RUN + 1))
        if [ "${on_path:-0}" = "${expect}" ]; then
            pass "nvm default resolves: ${label}"
        else
            fail "nvm default resolves: ${label}"
            printf '       expected on PATH: %s, got: %s\n' "${expect}" "${on_path:-0}"
        fi
    done <<'CASES'
bare version (24.18.0)|24.18.0\n|1
v-prefixed version (v24.18.0)|v24.18.0\n|1
lts alias chain (lts/* -> lts/krypton -> v24.18.0)|lts/*\n|1
alias file with no trailing newline|24.18.0|1
uninstalled version degrades to nothing|9.9.9\n|0
"system" degrades to nothing|system\n|0
empty alias file degrades to nothing||0
CASES

    # A missing alias file, and a wholly absent NVM_DIR, must both be silent
    # no-ops rather than injecting a nonexistent directory.
    rm -f "${fake}/alias/default"
    assert_eq "nvm default resolves: missing alias file adds no PATH entry" \
        "0" "$(staged_zsh -c "print -rl -- \$path | grep -c '${fake}' || true" NVM_DIR="${fake}")"
    assert_eq "nvm default resolves: absent NVM_DIR adds no PATH entry" \
        "0" "$(staged_zsh -c "print -rl -- \$path | grep -c '${STAGE}/nosuchnvm' || true" \
                NVM_DIR="${STAGE}/nosuchnvm")"
}

# path_helper re-introduces entries .zshenv already added; the dedup must run
# after it, in .zprofile, not only in .zshenv.
check_login_path_has_no_duplicates() {
    local path_str dupes
    path_str="$(staged_zsh -lc 'printf %s "$PATH"')"
    dupes="$(printf '%s' "${path_str}" | tr ':' '\n' | sort | uniq -d | tr '\n' ' ')"
    assert_eq "login shell PATH contains no duplicate entries" "" "${dupes%% }"
}

run_all() {
    bold "Shell startup contract (issue #176)"; printf '\n'
    printf '  dotfiles under test: %s\n\n' "${MACOS_DIR}"

    warm_completion_cache
    LOGIN_TOOLS="$(resolve_tools_in -lc)"
    ILOGIN_TOOLS="$(resolve_tools_in -lic)"
    BARE_TOOLS="$(resolve_tools_in -c)"

    check_login_shell_resolves_homebrew_bash
    check_login_shell_bash_has_readarray
    check_noninteractive_shell_sees_tools
    check_ssh_auth_sock_preserved
    check_zshenv_has_no_heavy_init
    check_nvm_default_resolution
    check_noninteractive_startup_is_fast
    check_login_path_has_no_duplicates

    printf '\n'
    bold "Results"; printf ': %d run, ' "${TESTS_RUN}"
    green "${TESTS_PASSED} passed"; printf ', '
    red "${TESTS_FAILED} failed"; printf ', %d skipped\n' "${TESTS_SKIPPED}"
    [ "${TESTS_FAILED}" -eq 0 ]
}

# --- Main ---

main() {
    if [ "$(uname -s)" != "Darwin" ]; then
        printf 'smoketest_shell_env: macOS-only (path_helper); skipping on %s\n' "$(uname -s)"
        exit 0
    fi
    stage_dotfiles
    run_all
}

main "$@"
