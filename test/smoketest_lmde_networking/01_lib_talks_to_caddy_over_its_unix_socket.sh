#!/usr/bin/env bash
# 01_lib_talks_to_caddy_over_its_unix_socket.sh
# Given Caddy's admin API answering only on a unix socket, with its http
# and tls apps not yet configured, When a cluster registers its vhost
# through lib.sh, Then every admin call travels over that socket: the
# liveness check, the http app and server init, the route POST naming the
# cluster's wildcard host and ingress port, the tls app init and the
# internal-issuer policy for that host; and unregistering sends the DELETE
# the same way. The fake is the only endpoint there is, so a call that
# left the socket could not reach it (Issue#465).

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
    assert_request "GET /config/ " "liveness check over the socket (exact line, not a sibling path)"
    assert_request 'POST /config/apps/http {"servers": {"srv0": {"listen": [":80", ":443"], "routes": []}}}' "http app and server init"
    assert_contains "${log}" "POST /config/apps/http/servers/srv0/routes" "route added over the socket"
    assert_contains "${log}" '"*.lmde.localhost"' "the wildcard host"
    assert_contains "${log}" '127.0.0.1:32100' "the ingress port"
    assert_request 'POST /config/apps/tls {"automation": {"policies": []}}' "tls app init"
    assert_request 'POST /config/apps/tls/automation/policies {"subjects": ["*.lmde.localhost"], "issuers": [{"module": "internal"}]}' "internal-issuer policy for the host"
    assert_request "DELETE /id/lmde_cluster_lmde " "route removed over the socket"
    assert_contains "${out}" "Registered vhost *.lmde.localhost -> 127.0.0.1:32100" "lib reports the registration"
}

main "$@"
