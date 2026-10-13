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
    WORK="$(mktemp -d "${TMPDIR:-/tmp}/lmde-net.XXXXXX")"
    trap fixture_cleanup EXIT INT TERM HUP
    SOCKET="${WORK}/caddy-admin.sock"
    REQUEST_LOG="${WORK}/requests.log"
    : > "${REQUEST_LOG}"
}

# start_fake_caddy -- an HTTP server on SOCKET that logs "METHOD PATH BODY"
# per request and answers 200 with a JSON body ({} for most paths, and a
# 404 for /id/<route> until that route was POSTed).
start_fake_caddy() {
    /usr/bin/python3 - "${SOCKET}" "${REQUEST_LOG}" <<'PY' &
import json, os, sys
from http.server import BaseHTTPRequestHandler
from socketserver import UnixStreamServer
sock, log = sys.argv[1], sys.argv[2]
routes = {}
class H(BaseHTTPRequestHandler):
    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n).decode() if n else ""
    def _reply(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def _handle(self):
        body = self._body()
        with open(log, "a") as f: f.write(f"{self.command} {self.path} {body}\n")
        if self.path.startswith("/id/"):
            rid = self.path[4:]
            if self.command == "GET": return self._reply(200, routes[rid]) if rid in routes else self._reply(404, {})
            if self.command == "PATCH": routes[rid] = json.loads(body); return self._reply(200, {})
            if self.command == "DELETE": routes.pop(rid, None); return self._reply(200, {})
        if self.command == "POST" and self.path.endswith("/routes"):
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
assert_contains() { [[ "$1" == *"$2"* ]] || fail "${3:-}: expected '$2' in:
$1"; }
assert_not_contains() { [[ "$1" != *"$2"* ]] || fail "${3:-}: did not expect '$2' in:
$1"; }
