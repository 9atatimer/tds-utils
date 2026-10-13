#!/usr/bin/env bash
# 02_deadline_does_not_cancel_the_load.sh
# Given an upstream still loading (silent for 3 s) and a 1 s deadline, When
# the caller has had the deadline answer, Then the route keeps the upstream
# request open until the upstream answers. ollama 0.40 aborts a load whose
# requester disconnects (verified 2026-10-12: "client connection closed
# before llama-server finished loading, aborting load"), so dropping the
# upstream at the deadline would make every retry start the load again.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

main() {
    require_haproxy
    fixture_setup
    start_upstream silent 3
    start_proxy
    local code
    code="$(curl -s -m 10 -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PROXY_PORT}/v1/models")"
    assert_eq "${code}" "507" "caller gets the deadline answer"

    wait_for "the fake upstream's report" test -s "${RECORD}"
    assert_contains "$(cat "${RECORD}")" "held" "upstream held open past the deadline (record: $(cat "${RECORD}"))"
}

main "$@"
