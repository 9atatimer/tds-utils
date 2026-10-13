#!/bin/zsh -f
# healthcheck.sh -- the Ollama Gateway's component healthcheck (`lmde
# status`, `lmde doctor`; docs/design/OLLAMA-GATEWAY.DESIGN.md, State
# Machine and Key Decisions Q8).
#
# One line per check, "<check>: OK", "<check>: DEGRADED (<why>)" or
# "<check>: SKIPPED (<why>)"; exits non-zero if any check is DEGRADED.
#
#   external-ollama  something answers GET /api/version on 127.0.0.1:<ollama-port>
#   deadline-proxy   GET /v1/models on 127.0.0.1:<proxy-port> answers with the
#                    route's X-LMDE-Route: ollama-gateway header
#   edge             Q8 (a), origin-port drift: an allow-listed request
#                    through the tunnel must reach the deadline proxy. GET
#                    <edge>/v1/models with the consumer credential must answer
#                    with the route's header -- any status, the 507 deadline
#                    answer included, since only the proxy adds it. An answer
#                    without it is DRIFT: the edge's origin_port reaches some
#                    other listener, bypassing the proxy and the sandbox.
#
# The edge check runs only when configured, typically through `op run` with
# an env file mapping the consumer's 1Password item (the item and the URL
# are named in tds-internal, not in this public repo):
#   OLLAMA_GATEWAY_EDGE_URL               https://<gateway-host>
#   OLLAMA_GATEWAY_CLIENT_ID_HEADER       the item's client id header name
#   OLLAMA_GATEWAY_CLIENT_ID              the item's client id
#   OLLAMA_GATEWAY_CLIENT_SECRET_HEADER   the item's client secret header name
#   OLLAMA_GATEWAY_CLIENT_SECRET          the item's client secret
# Header names come from the item, never from this script (Credential
# contract). The credential reaches curl on stdin (-H @-), never argv.

set -euo pipefail

# --- Constants ---

readonly COMPONENT_DIR="${0:A:h}"
readonly ROUTE_HEADER="x-lmde-route: ollama-gateway"
readonly -a EDGE_VARS=(
    OLLAMA_GATEWAY_CLIENT_ID_HEADER OLLAMA_GATEWAY_CLIENT_ID
    OLLAMA_GATEWAY_CLIENT_SECRET_HEADER OLLAMA_GATEWAY_CLIENT_SECRET
)

integer DEGRADED=0

# --- Reporting ---

ok() { print -r -- "$1: OK${2:+ ($2)}"; }
degraded() { print -r -- "$1: DEGRADED ($2)"; DEGRADED+=1; }
skipped() { print -r -- "$1: SKIPPED ($2)"; }

# --- Pure helpers ---

# status_of <response headers> -- the HTTP status code of the first line.
status_of() {
    local first="${${(f)1}[1]}"
    print -r -- "${${(s: :)first}[2]:-}"
}

# --- Predicates ---

# carries_route_header <response headers> -- did the gateway route answer?
carries_route_header() {
    [[ "${${1:l}//$'\r'/}" == *"${ROUTE_HEADER}"* ]]
}

# --- Effectful helpers ---

# fetch_headers <url> -- response headers of a GET, or fail.
fetch_headers() {
    curl -sS -m 15 -D - -o /dev/null "$1" 2>/dev/null
}

# fetch_headers_with_credential <url> -- as fetch_headers, with the consumer
# credential's two headers fed to curl on stdin.
fetch_headers_with_credential() {
    print -r -- "${OLLAMA_GATEWAY_CLIENT_ID_HEADER}: ${OLLAMA_GATEWAY_CLIENT_ID}
${OLLAMA_GATEWAY_CLIENT_SECRET_HEADER}: ${OLLAMA_GATEWAY_CLIENT_SECRET}" \
        | curl -sS -m 30 -H @- -D - -o /dev/null "$1" 2>/dev/null
}

# --- Checks ---

check_external_ollama() {
    local headers
    if headers="$(fetch_headers "http://127.0.0.1:${OLLAMA_GATEWAY_OLLAMA_PORT}/api/version")" \
        && [[ "$(status_of "${headers}")" == 200 ]]; then
        ok external-ollama "127.0.0.1:${OLLAMA_GATEWAY_OLLAMA_PORT}"
    else
        degraded external-ollama "nothing answers on 127.0.0.1:${OLLAMA_GATEWAY_OLLAMA_PORT}; launchctl print gui/$(id -u)/com.tds.lmde.ollama-gateway.ollama, ~/Library/Logs/ollama-gateway/ollama.log"
    fi
}

check_deadline_proxy() {
    local headers url="http://127.0.0.1:${OLLAMA_GATEWAY_PROXY_PORT}/v1/models"
    if ! headers="$(fetch_headers "${url}")"; then
        degraded deadline-proxy "nothing answers on 127.0.0.1:${OLLAMA_GATEWAY_PROXY_PORT}; is com.tds.lmde.proxy-layer loaded?"
    elif ! carries_route_header "${headers}"; then
        degraded deadline-proxy "127.0.0.1:${OLLAMA_GATEWAY_PROXY_PORT} answered without the route header: another listener holds the proxy port"
    else
        ok deadline-proxy "127.0.0.1:${OLLAMA_GATEWAY_PROXY_PORT}, HTTP $(status_of "${headers}")"
    fi
}

check_edge() {
    local url="${OLLAMA_GATEWAY_EDGE_URL:-}" headers code var
    local -a missing=()
    if [[ -z "${url}" ]]; then
        skipped edge "OLLAMA_GATEWAY_EDGE_URL not set; the drift check needs the edge and a consumer credential"
        return 0
    fi
    for var in "${EDGE_VARS[@]}"; do
        [[ -n "${(P)var:-}" ]] || missing+=("${var}")
    done
    if (( ${#missing} > 0 )); then
        degraded edge "credential not configured: ${(j:, :)missing}"
        return 0
    fi
    if ! headers="$(fetch_headers_with_credential "${url%/}/v1/models")"; then
        degraded edge "no answer from ${url}"
        return 0
    fi
    code="$(status_of "${headers}")"
    if carries_route_header "${headers}"; then
        ok edge "the tunnel reaches the deadline proxy, HTTP ${code}"
    elif [[ "${code}" == 2?? ]]; then
        degraded edge "DRIFT: an allow-listed request through the tunnel was answered (HTTP ${code}) by something other than the deadline proxy; check origin_port against OLLAMA_GATEWAY_PROXY_PORT=${OLLAMA_GATEWAY_PROXY_PORT}"
    else
        degraded edge "HTTP ${code} without the route header (302/403: Access refused the credential; 502: nothing on the origin port; 530: no connector)"
    fi
}

# --- Entry point ---

main() {
    if [[ "$(uname -s)" != "Darwin" ]]; then
        print -r -- "ollama-gateway: not applicable (macOS only)"
        return 0
    fi
    # shellcheck disable=SC1091
    source "${COMPONENT_DIR}/gateway.env"
    check_external_ollama
    check_deadline_proxy
    check_edge
    (( DEGRADED == 0 ))
}

main "$@"
