#!/usr/bin/env bash
# 06_no_bodies_on_disk_and_no_caps.sh
# Given a request with a large body (2 MiB) carrying a marker, When it goes
# through the gateway route, Then the upstream receives it whole (no
# payload cap, Q12) and the marker appears nowhere the layer writes: not in
# its log and not under its root (Q10: no request or response bodies on
# disk).

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

main() {
    require_haproxy
    fixture_setup
    start_upstream record
    start_proxy
    local marker="CODE-UNDER-REVIEW-$$-MARKER" body="${ROOT}/../body.$$" code
    {
        printf '{"model":"m","messages":[{"role":"user","content":"%s ' "${marker}"
        head -c 2097152 /dev/zero | tr '\0' 'x'
        printf '"}]}'
    } > "${body}"
    code="$(curl -s -m 10 -o /dev/null -w '%{http_code}' --data-binary @"${body}" \
        "http://127.0.0.1:${PROXY_PORT}/v1/chat/completions")"
    rm -f "${body}"
    assert_eq "${code}" "200" "a 2 MiB request is forwarded"
    wait_for "the upstream record" test -s "${RECORD}"
    grep -q -- "${marker}" "${RECORD}" || fail "the upstream never got the body"
    [[ "$(wc -c < "${RECORD}")" -gt 2097152 ]] || fail "the upstream got a truncated body"
    rm -f "${RECORD}"
    if grep -rl -- "${marker}" "${ROOT}" >/dev/null 2>&1; then
        fail "the request body reached disk under the layer root: $(grep -rl -- "${marker}" "${ROOT}")"
    fi
}

main "$@"
