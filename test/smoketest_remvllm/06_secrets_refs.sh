#!/usr/bin/env bash
# 06_secrets_refs.sh
# Given the shipped remvllm.conf, Then every REMVLLM_*_OP_* default is empty
# and no op:// reference is in the file (this repo is public; a reference
# names a vault and an item). Given a provider reference empty or not an
# op:// path, When secrets_preflight runs, Then it fails naming the variable
# before `op` is consulted; given all three set, the refs check passes.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.sh"
# shellcheck source=../../ops/terraform/remvllm/lib/secrets.sh
source "${LIB_DIR}/secrets.sh"

CONF="${REPO_DIR}/ops/terraform/remvllm/remvllm.conf"

main() {
    # Global (not local) so the EXIT trap can see it after main returns.
    tmp="$(mktemp -d)"
    trap 'rm -rf "${tmp}"' EXIT

    # --- the shipped defaults are empty ---
    if grep -q 'op://[A-Za-z0-9]' "${CONF}"; then
        echo "FAIL: remvllm.conf carries an op:// reference"; return 1
    fi
    local line
    while IFS= read -r line; do
        case "${line}" in
            *'=""'*) ;;
            *) echo "FAIL: non-empty default: ${line}"; return 1 ;;
        esac
    done < <(grep -E '^REMVLLM_[A-Z_]*_OP_[A-Z_]*[[:space:]]*=' "${CONF}" | sed -E 's/[[:space:]]*=[[:space:]]*/=/')

    # --- preflight refuses an empty or malformed reference, before op ---
    mkdir -p "${tmp}/bin"
    # The fake records every call; the refs check must run before any.
    printf '#!/usr/bin/env bash\necho "$*" >> "${OP_CALLS:?}"; echo "op must not be consulted" >&2; exit 97\n' > "${tmp}/bin/op"
    export OP_CALLS="${tmp}/op.calls"
    chmod +x "${tmp}/bin/op"
    export PATH="${tmp}/bin:${PATH}"
    export REMVLLM_PROVIDER=spheron
    export REMVLLM_SPHERON_OP_TOKEN="" REMVLLM_SPHERON_OP_SSH_KEY="" REMVLLM_SPHERON_OP_SSH_PUBKEY=""

    local err
    if err="$(secrets_preflight 2>&1)"; then
        echo "FAIL: preflight passed with empty references"; return 1
    fi
    local var
    for var in REMVLLM_SPHERON_OP_TOKEN REMVLLM_SPHERON_OP_SSH_KEY REMVLLM_SPHERON_OP_SSH_PUBKEY; do
        [[ "${err}" == *"${var} is not set"* ]] || { echo "FAIL: ${var} not named as unset: ${err}"; return 1; }
    done
    [[ ! -e "${OP_CALLS}" ]] || { echo "FAIL: op was consulted before the refs check"; return 1; }

    export REMVLLM_SPHERON_OP_TOKEN="sk-a-bare-secret" \
           REMVLLM_SPHERON_OP_SSH_KEY="op://v/i/private_key" \
           REMVLLM_SPHERON_OP_SSH_PUBKEY="op://v/i/public_key"
    if err="$(secrets_preflight 2>&1)"; then
        echo "FAIL: preflight accepted a bare value"; return 1
    fi
    [[ "${err}" == *"REMVLLM_SPHERON_OP_TOKEN must be an op:// reference"* ]] || { echo "FAIL: bare value not named: ${err}"; return 1; }
    [[ "${err}" != *"sk-a-bare-secret"* ]] || { echo "FAIL: the bare value was echoed"; return 1; }

    # --- all three set: the refs check passes (op itself stays faked out) ---
    export REMVLLM_SPHERON_OP_TOKEN="op://v/i/credential"
    secrets_require_refs || { echo "FAIL: refs check failed with all three set"; return 1; }
    [[ ! -e "${OP_CALLS}" ]] || { echo "FAIL: the refs check itself consulted op"; return 1; }

    # --- the check keys on REMVLLM_PROVIDER, not on spheron ---
    export REMVLLM_PROVIDER=otherprov
    if err="$(secrets_require_refs 2>&1)"; then
        echo "FAIL: another provider's unset references passed"; return 1
    fi
    [[ "${err}" == *"REMVLLM_OTHERPROV_OP_TOKEN is not set"* ]] || { echo "FAIL: provider name not expanded: ${err}"; return 1; }
    export REMVLLM_OTHERPROV_OP_TOKEN="op://v/o/credential" \
           REMVLLM_OTHERPROV_OP_SSH_KEY="op://v/o/private_key" \
           REMVLLM_OTHERPROV_OP_SSH_PUBKEY="op://v/o/public_key"
    secrets_require_refs || { echo "FAIL: refs check failed for another provider with all three set"; return 1; }
    echo "ok"
}

main "$@"
