#!/usr/bin/env bash
# 01_lib_talks_to_caddy_over_its_unix_socket.sh
# Given Caddy's admin API answering only on a unix socket, When a cluster
# registers its vhost through lib.sh, Then every admin call travels over
# that socket (the fake logs the route POST, the TLS policy and the server
# init) and the route names the cluster's wildcard host and ingress port;
# unregistering sends the DELETE the same way. No TCP port is involved
# (Issue#465).

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

main() {
    fixture_setup
    start_fake_caddy
    local out
    out="$(CADDY_ADMIN_SOCKET="${SOCKET}" bash -c "set -euo pipefail; source '${LIB}'; caddy_is_running && register_cluster_vhost lmde 32100 && unregister_cluster_vhost lmde" 2>&1)" \
        || fail "lib.sh failed against the fake socket: ${out}"
    local log
    log="$(cat "${REQUEST_LOG}")"
    assert_contains "${log}" "GET /config/" "liveness check over the socket"
    assert_contains "${log}" "POST /config/apps/http/servers/srv0/routes" "route added over the socket"
    assert_contains "${log}" '"*.lmde.localhost"' "the wildcard host"
    assert_contains "${log}" '127.0.0.1:32100' "the ingress port"
    assert_contains "${log}" "DELETE /id/lmde_cluster_lmde" "route removed over the socket"
    assert_contains "${out}" "Registered vhost *.lmde.localhost -> 127.0.0.1:32100" "lib reports the registration"
}

main "$@"
