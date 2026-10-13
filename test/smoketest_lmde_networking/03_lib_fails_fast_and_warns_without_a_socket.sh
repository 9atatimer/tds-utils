#!/usr/bin/env bash
# 03_lib_fails_fast_and_warns_without_a_socket.sh
# Given no admin socket at the configured path, When lib.sh is asked
# whether Caddy is running and then to register a vhost, Then the liveness
# check fails at once (no connect timeout to wait out) and the
# registration warns, names the socket, and succeeds, so a cluster
# bootstrap is not blocked by a missing host proxy; nothing is sent
# anywhere else.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

main() {
    fixture_setup
    local started ended out status=0
    started="$(date +%s)"
    out="$(CADDY_ADMIN_SOCKET="${SOCKET}" bash -c "set -euo pipefail; source '${LIB}'; if caddy_is_running; then echo running; else echo not-running; fi; register_cluster_vhost lmde 32100" 2>&1)" || status=$?
    ended="$(date +%s)"
    assert_contains "${out}" "not-running" "caddy_is_running reports the absent socket"
    [[ "${status}" -eq 0 ]] || fail "register must succeed (warn) without Caddy; exit ${status}, output:
${out}"
    assert_contains "${out}" "WARNING: Caddy admin API unreachable at ${SOCKET}" "the warning names the socket"
    assert_not_contains "${out}" "Registered vhost" "nothing was registered"
    (( ended - started < 3 )) || fail "the absent-socket path took $(( ended - started ))s; it must fail fast"
    [[ ! -e "${REQUEST_LOG}" || ! -s "${REQUEST_LOG}" ]] || fail "requests were logged with no fake running"
}

main "$@"
