#!/usr/bin/env bash
# config.sh -- shared fixtures for the LMDE networking smoke tests
# (lmde/components/networking; docs/design/LMDE.DESIGN.md section 4).
#
# A fake Caddy admin API answers on a unix socket in a throwaway dir and
# records every request it receives, so lib.sh's client is driven without
# Caddy, without TCP, and without touching the real /opt/homebrew/etc.
# Sourcing is side-effect-free; call fixture_setup from a scenario.

set -euo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${TEST_DIR}/../.." && pwd)"
COMPONENT_DIR="${REPO_DIR}/lmde/components/networking"
LIB="${COMPONENT_DIR}/lib.sh"
SETUP="${COMPONENT_DIR}/setup.sh"

WORK=""
SOCKET=""
REQUEST_LOG=""
FAKE_PID=""

# require_macos -- exit 0 with a skip line on anything but macOS: the
# component targets Homebrew Caddy, and the fixture uses BSD stat and the
# system python.
require_macos() {
    if [[ "$(uname -s)" != "Darwin" ]]; then
        echo "skip: not macOS (Homebrew Caddy, BSD stat and /usr/bin/python3 are assumed)"
        exit 0
    fi
}

fixture_cleanup() {
    if [[ -n "${FAKE_PID}" ]] && kill -0 "${FAKE_PID}" 2>/dev/null; then
        kill "${FAKE_PID}" 2>/dev/null || true
        sleep 0.2
        kill -9 "${FAKE_PID}" 2>/dev/null || true
    fi
    [[ -n "${WORK}" && -d "${WORK}" ]] && rm -rf "${WORK}"
    return 0
}

# fixture_setup -- a short-pathed work dir (a unix socket path is limited to
# about 100 bytes on macOS), the socket path and the request log.
fixture_setup() {
    require_macos
    WORK="$(mktemp -d "${TMPDIR:-/tmp}/lmde-net.XXXXXX")"
    trap fixture_cleanup EXIT INT TERM HUP
    SOCKET="${WORK}/caddy-admin.sock"
    REQUEST_LOG="${WORK}/requests.log"
    : > "${REQUEST_LOG}"
}

# start_fake_caddy -- an HTTP server on SOCKET that logs "METHOD PATH BODY"
# per request and models the slice of Caddy's config API lib.sh uses: the
# http app, its server srv0 and the tls app are absent (404) until POSTed;
# routes live under /id/<route>; the TLS automation policies are a list
# that a POST appends to. Everything else answers 200 {}.
start_fake_caddy() {
    /usr/bin/python3 - "${SOCKET}" "${REQUEST_LOG}" <<'PY' &
import json, os, sys
from http.server import BaseHTTPRequestHandler
from socketserver import UnixStreamServer
sock, log = sys.argv[1], sys.argv[2]
routes, apps, policies = {}, set(), []
class H(BaseHTTPRequestHandler):
    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n).decode() if n else ""
    def _reply(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def _handle(self):
        body = self._body(); m, p = self.command, self.path
        with open(log, "a") as f: f.write(f"{m} {p} {body}\n")
        if p.startswith("/id/"):
            rid = p[4:]
            if m == "GET": return self._reply(200, routes[rid]) if rid in routes else self._reply(404, {})
            if m == "PATCH": routes[rid] = json.loads(body); return self._reply(200, {})
            if m == "DELETE": routes.pop(rid, None); return self._reply(200, {})
        if p in ("/config/apps/http", "/config/apps/http/servers/srv0", "/config/apps/tls"):
            key = "http" if p.startswith("/config/apps/http") else "tls"
            if m == "POST": apps.add(key); return self._reply(200, {})
            return self._reply(200, {}) if key in apps else self._reply(404, {})
        if p == "/config/apps/tls/automation/policies":
            if m == "POST": policies.append(json.loads(body)); return self._reply(200, {})
            return self._reply(200, policies)
        if m == "POST" and p.endswith("/routes"):
            r = json.loads(body); routes[r["@id"]] = r; return self._reply(200, {})
        return self._reply(200, {"ok": True})
    do_GET = do_POST = do_PATCH = do_DELETE = _handle
    def log_message(self, *a): pass
class S(UnixStreamServer):
    def server_bind(self):
        super().server_bind(); os.chmod(sock, 0o600)
S(sock, H).serve_forever()
PY
    FAKE_PID=$!
    local tries=0
    while [[ ! -S "${SOCKET}" ]] && (( tries < 50 )); do sleep 0.1; tries=$((tries + 1)); done
    [[ -S "${SOCKET}" ]] || fail "fake caddy did not create ${SOCKET}"
}

fail() { echo "FAIL: $*"; exit 1; }
# assert_request <exact log line> <msg> -- the fake logged exactly this
# "METHOD PATH BODY" line (a substring would also match a sibling path).
assert_request() { grep -q -x -F -- "$1" "${REQUEST_LOG}" || fail "${2:-}: no request line '$1' in:
$(cat "${REQUEST_LOG}")"; }
assert_contains() { [[ "$1" == *"$2"* ]] || fail "${3:-}: expected '$2' in:
$1"; }
assert_not_contains() { [[ "$1" != *"$2"* ]] || fail "${3:-}: did not expect '$2' in:
$1"; }
