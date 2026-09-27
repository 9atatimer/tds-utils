#!/usr/bin/env python3
"""serve.py -- spike: loopback stand-in for the machine-side half.

GET /sessions?repo=<owner/repo>&branch=<branch> runs A-map.zsh on each
request and answers JSON. Holds no state; the point is to measure whether
a stateless answer is fast enough to sit behind a click, and (for spike C)
which CORS / Private Network Access headers the browser insists on.

    serve.py [--port 47321] [--socket TMUX_SOCKET] [--fake sessions.tsv] [--no-cors]

Binds 127.0.0.1 only.
"""

import argparse
import json
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
OPTS = None


# --- Action functions ---
def run_map(repo, branch):
    cmd = ["zsh", str(HERE / "A-map.zsh"), "-r", repo, "-b", branch]
    if OPTS.socket:
        cmd += ["-L", OPTS.socket]
    return subprocess.run(cmd, capture_output=True, text=True, check=False).stdout


def read_fake(repo, branch):
    rows = Path(OPTS.fake).read_text().splitlines()
    keep = []
    for row in rows:
        cols = row.split("\t")
        if len(cols) == 4 and cols[2] == repo and cols[3] == branch:
            keep.append(row)
    return "\n".join(keep)


def to_json(tsv):
    out = []
    for row in tsv.splitlines():
        sid, name, repo, branch = row.split("\t")
        out.append({"session_id": sid, "name": name, "repo": repo, "branch": branch})
    return out


# --- Flow ---
class Handler(BaseHTTPRequestHandler):
    def cors(self):
        if OPTS.no_cors:
            return
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def trace(self):
        h = self.headers
        sys.stderr.write(
            f"{self.command} {self.path} origin={h.get('Origin')} "
            f"sec-fetch-mode={h.get('Sec-Fetch-Mode')} sec-fetch-site={h.get('Sec-Fetch-Site')} "
            f"acr-private-network={h.get('Access-Control-Request-Private-Network')}\n"
        )

    def do_OPTIONS(self):
        self.trace()
        self.send_response(204)
        self.cors()
        self.end_headers()

    def do_GET(self):
        self.trace()
        url = urlparse(self.path)
        if url.path != "/sessions":
            self.send_response(404)
            self.end_headers()
            return
        q = parse_qs(url.query)
        repo = q.get("repo", [""])[0]
        branch = q.get("branch", [""])[0]
        t0 = time.monotonic()
        tsv = read_fake(repo, branch) if OPTS.fake else run_map(repo, branch)
        body = json.dumps(to_json(tsv)).encode()
        ms = int((time.monotonic() - t0) * 1000)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Elapsed-Ms", str(ms))
        self.cors()
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            sys.stderr.write("client closed before reading the body\n")
            return
        sys.stderr.write(f"/sessions repo={repo} branch={branch} -> {len(body)}B in {ms}ms\n")

    def log_message(self, *_):
        pass


def main():
    global OPTS
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=47321)
    ap.add_argument("--socket", default="")
    ap.add_argument("--fake", default="")
    ap.add_argument("--no-cors", action="store_true")
    OPTS = ap.parse_args()
    srv = HTTPServer(("127.0.0.1", OPTS.port), Handler)
    sys.stderr.write(f"serving on http://127.0.0.1:{OPTS.port} cors={'off' if OPTS.no_cors else 'on'}\n")
    srv.serve_forever()


if __name__ == "__main__":
    main()
