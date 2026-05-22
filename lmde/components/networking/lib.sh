#!/usr/bin/env bash
# lib.sh -- Shared host-networking helpers for the LMDE networking component.
#
# Purpose:     Owns the host edge of the *.{cluster}.localhost ingress
#              pattern -- registering Caddy reverse-proxy routes that forward
#              a cluster's wildcard vhost to that cluster's ingress port.
#              See docs/design/LMDE-OBSERVABILITY.DESIGN.md, section 4.
# Usage:       Sourced by a cluster's setup.sh; not executable on its own.
# Note:        Strict mode is intentionally NOT set here -- the sourcing
#              script owns `set -euo pipefail`.

# --- Shared state ---

CADDY_ADMIN_URL="${CADDY_ADMIN_URL:-http://localhost:2019}"

# --- Logging ---

log_info() {
    echo "[$(date +'%Y-%m-%dT%H:%M:%S%z')] [networking] $*"
}

# --- Caddy helpers ---

# caddy_is_running -- succeeds if the Caddy admin API answers.
caddy_is_running() {
    curl -sf --max-time 2 "${CADDY_ADMIN_URL}/config/" >/dev/null 2>&1
}

# _caddy_ensure_server -- ensure the http app and server srv0 exist, listening
# on :80 and :443. srv0 is the default server name Caddy assigns. Private.
_caddy_ensure_server() {
    if ! curl -sf "${CADDY_ADMIN_URL}/config/apps/http" >/dev/null 2>&1; then
        log_info "Initializing Caddy http app..."
        curl -sf -X POST -H "Content-Type: application/json" \
            -d '{"servers": {"srv0": {"listen": [":80", ":443"], "routes": []}}}' \
            "${CADDY_ADMIN_URL}/config/apps/http" >/dev/null || return 1
        return 0
    fi
    if ! curl -sf "${CADDY_ADMIN_URL}/config/apps/http/servers/srv0" >/dev/null 2>&1; then
        log_info "Initializing Caddy server srv0..."
        curl -sf -X POST -H "Content-Type: application/json" \
            -d '{"listen": [":80", ":443"], "routes": []}' \
            "${CADDY_ADMIN_URL}/config/apps/http/servers/srv0" >/dev/null || return 1
    fi
}

# _caddy_ensure_internal_tls <subject> -- ensure a TLS automation policy with
# the internal issuer covers <subject>. Idempotent. Private.
_caddy_ensure_internal_tls() {
    local subject="$1"
    if ! curl -sf "${CADDY_ADMIN_URL}/config/apps/tls" >/dev/null 2>&1; then
        curl -sf -X POST -H "Content-Type: application/json" \
            -d '{"automation": {"policies": []}}' \
            "${CADDY_ADMIN_URL}/config/apps/tls" >/dev/null || return 1
    fi
    local policies
    policies=$(curl -sf "${CADDY_ADMIN_URL}/config/apps/tls/automation/policies" 2>/dev/null || echo "[]")
    if [[ "${policies}" == *"\"${subject}\""* ]]; then
        return 0
    fi
    curl -sf -X POST -H "Content-Type: application/json" \
        -d "{\"subjects\": [\"${subject}\"], \"issuers\": [{\"module\": \"internal\"}]}" \
        "${CADDY_ADMIN_URL}/config/apps/tls/automation/policies" >/dev/null || return 1
}

# register_cluster_vhost <cluster-alias> <ingress-port> -- route the wildcard
# vhost *.{alias}.localhost through Caddy to 127.0.0.1:<ingress-port>, the host
# port mapped to that cluster's ingress-nginx controller.
#
# Idempotent: re-running updates the existing route in place. If Caddy is not
# reachable the function logs a warning and succeeds, so a cluster bootstrap
# is not blocked by a missing host proxy.
register_cluster_vhost() {
    local alias="$1"
    local port="$2"

    if [[ -z "${alias}" || -z "${port}" ]]; then
        echo "ERROR: register_cluster_vhost requires <cluster-alias> <ingress-port>" >&2
        return 1
    fi
    if [[ ! "${alias}" =~ ^[a-z0-9-]+$ ]]; then
        echo "ERROR: cluster alias must match [a-z0-9-]+ (got: ${alias})" >&2
        return 1
    fi
    if [[ ! "${port}" =~ ^[0-9]+$ ]]; then
        echo "ERROR: ingress-port must be numeric (got: ${port})" >&2
        return 1
    fi

    if ! caddy_is_running; then
        log_info "WARNING: Caddy admin API unreachable at ${CADDY_ADMIN_URL};" \
                 "skipping vhost registration for *.${alias}.localhost"
        return 0
    fi

    if ! _caddy_ensure_server; then
        echo "ERROR: could not initialize the Caddy http server" >&2
        return 1
    fi

    local host="*.${alias}.localhost"
    local route_id="lmde_cluster_${alias}"
    local route
    route=$(cat <<EOF
{
  "@id": "${route_id}",
  "match": [{ "host": ["${host}"] }],
  "handle": [{
    "handler": "reverse_proxy",
    "upstreams": [{ "dial": "127.0.0.1:${port}" }]
  }],
  "terminal": true
}
EOF
    )

    if curl -sf "${CADDY_ADMIN_URL}/id/${route_id}" >/dev/null 2>&1; then
        log_info "Updating Caddy route ${host} -> 127.0.0.1:${port}"
        if ! curl -sf -X PATCH -H "Content-Type: application/json" \
            -d "${route}" "${CADDY_ADMIN_URL}/id/${route_id}" >/dev/null; then
            echo "ERROR: failed to update Caddy route ${route_id}" >&2
            return 1
        fi
    else
        log_info "Adding Caddy route ${host} -> 127.0.0.1:${port}"
        if ! curl -sf -X POST -H "Content-Type: application/json" \
            -d "${route}" "${CADDY_ADMIN_URL}/config/apps/http/servers/srv0/routes" >/dev/null; then
            echo "ERROR: failed to add Caddy route ${route_id}" >&2
            return 1
        fi
    fi

    if ! _caddy_ensure_internal_tls "${host}"; then
        log_info "WARNING: could not set the internal TLS policy for ${host}"
    fi

    log_info "Registered vhost *.${alias}.localhost -> 127.0.0.1:${port}"
}

# unregister_cluster_vhost <cluster-alias> -- remove a cluster's Caddy route.
# Idempotent; a missing route is not an error.
unregister_cluster_vhost() {
    local alias="$1"
    if [[ -z "${alias}" ]]; then
        echo "ERROR: unregister_cluster_vhost requires <cluster-alias>" >&2
        return 1
    fi
    curl -sf -X DELETE "${CADDY_ADMIN_URL}/id/lmde_cluster_${alias}" >/dev/null 2>&1 || true
    log_info "Unregistered vhost *.${alias}.localhost (if present)"
}
