#!/usr/bin/env python3
"""fixture_server.py -- serve fixture.html as https://github.com/... for spike C.

Chromium is launched with --host-resolver-rules="MAP github.com 127.0.0.1"
and --ignore-certificate-errors, so this stands in for github.com without
Playwright request interception (which pauses the extension's service
worker requests too). Needs port 443, so root or a port capability.

    fixture_server.py <certdir>     (cert.pem + key.pem inside)
"""

import ssl
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
BODY = (HERE / "fixture.html").read_bytes()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        self.wfile.write(BODY)

    def log_message(self, *_):
        pass


def main():
    certdir = Path(sys.argv[1])
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certdir / "cert.pem", certdir / "key.pem")
    srv = HTTPServer(("127.0.0.1", 443), Handler)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    sys.stderr.write("fixture on https://127.0.0.1:443 (as github.com)\n")
    srv.serve_forever()


if __name__ == "__main__":
    main()
