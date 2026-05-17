#!/usr/bin/env bash
# config.sh — shared environment + helpers for clai smoke tests
#
# Each scenario sources this, calls `init_scenario <name>` to mint a fresh fake
# HOME tree, then uses `write_hook`, `make_agent`, and `run_clai` to set up and
# exercise. All side effects land under ${SMOKE_TMP}/<scenario>/.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
CLAI_BIN="${REPO_DIR}/bin/clai"

# init_scenario <name>
#
# Builds an isolated fake HOME under ${SMOKE_TMP}/<name>/home, exports it as
# HOME, and clears any inherited PATH so only the fake agent is found.
init_scenario() {
    local name="$1"
    export SCENARIO_DIR="${SMOKE_TMP}/${name}"
    export FAKE_HOME="${SCENARIO_DIR}/home"
    export FAKE_BIN="${SCENARIO_DIR}/bin"
    export SENTINEL="${SCENARIO_DIR}/sentinel.log"
    mkdir -p "${FAKE_HOME}" "${FAKE_BIN}"
    : > "${SENTINEL}"
    export HOME="${FAKE_HOME}"
    export PATH="${FAKE_BIN}:${PATH}"
}

# write_hook <dir> <agent> <stage> <basename> <content>
#
# Drops an executable hook at <dir>/clai.d/<agent>/<stage>/<basename>. <dir>
# is created if missing. Content is written verbatim; if empty, file is
# zero-byte (the override null-out marker).
write_hook() {
    local dir="$1"
    local agent="$2"
    local stage="$3"
    local name="$4"
    local content="$5"
    local target="${dir}/clai.d/${agent}/${stage}/${name}"
    mkdir -p "$(dirname "${target}")"
    printf '%s' "${content}" > "${target}"
    chmod +x "${target}"
}

# make_agent <name> [exit_code]
#
# Installs a fake agent at ${FAKE_BIN}/<name> that appends one line to
# ${SENTINEL} ("agent:<name> args:<argv>") and exits with the given code.
make_agent() {
    local name="$1"
    local rc="${2:-0}"
    local target="${FAKE_BIN}/${name}"
    cat > "${target}" <<EOF
#!/usr/bin/env bash
printf 'agent:%s args:%s\n' "${name}" "\$*" >> "${SENTINEL}"
exit ${rc}
EOF
    chmod +x "${target}"
}

# run_clai <cwd> <agent> [args...]
#
# cd into <cwd> (relative paths resolved under FAKE_HOME) and runs the real
# bin/clai with the rest of the args. Returns clai's exit code.
run_clai() {
    local cwd="$1"; shift
    case "${cwd}" in
        /*) ;;
        *) cwd="${FAKE_HOME}/${cwd}" ;;
    esac
    mkdir -p "${cwd}"
    ( cd "${cwd}" && "${CLAI_BIN}" "$@" )
}

export -f init_scenario write_hook make_agent run_clai
