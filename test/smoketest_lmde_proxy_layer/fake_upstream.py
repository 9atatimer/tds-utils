"""fake_upstream.py -- a stand-in for the external ollama behind the LMDE
proxy layer's gateway route, for test/smoketest_lmde_proxy_layer.

Usage: fake_upstream.py <port> <mode> <record-file> [<seconds>]

Modes:
  silent   accept one request and send nothing for <seconds>, watching the
           connection: records "closed-early <t>" if the proxy drops it, or
           "held <t>" if it stays open the whole time, then answers 200.
  stream   accept one request and answer at once: 200, chunked, two chunks.
  record   accept one request, record its full bytes, answer 200.

Writes "ready" to <record-file>.ready once listening, so the test can wait
on an event rather than a guess. Exits after one connection.
"""

from __future__ import annotations

import select
import socket
import sys
import time


def listen(port: int) -> socket.socket:
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(4)
    return srv


def read_request(conn: socket.socket) -> bytes:
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = conn.recv(65536)
        if not chunk:
            return data
        data += chunk
    head, _, body = data.partition(b"\r\n\r\n")
    length = 0
    for line in head.split(b"\r\n"):
        if line.lower().startswith(b"content-length:"):
            length = int(line.split(b":", 1)[1])
    while len(body) < length:
        chunk = conn.recv(65536)
        if not chunk:
            break
        body += chunk
    return head + b"\r\n\r\n" + body


def silent(conn: socket.socket, seconds: float, record: str) -> None:
    start = time.time()
    while time.time() - start < seconds:
        readable, _, _ = select.select([conn], [], [], 0.05)
        if readable:
            try:
                peek = conn.recv(1, socket.MSG_PEEK)
            except ConnectionError:
                peek = b""
            if not peek:
                write(record, "closed-early %.1f\n" % (time.time() - start))
                return
    write(record, "held %.1f\n" % (time.time() - start))
    try:
        conn.sendall(b"HTTP/1.1 200 OK\r\ncontent-length: 2\r\n\r\nok")
    except ConnectionError:
        pass


def stream(conn: socket.socket) -> None:
    conn.sendall(
        b"HTTP/1.1 200 OK\r\ncontent-type: application/x-ndjson\r\n"
        b"transfer-encoding: chunked\r\n\r\n"
        b"6\r\nfirst\n\r\n7\r\nsecond\n\r\n0\r\n\r\n"
    )


def write(path: str, text: str) -> None:
    with open(path, "a") as fh:
        fh.write(text)


def main(argv: list[str]) -> int:
    port, mode, record = int(argv[1]), argv[2], argv[3]
    seconds = float(argv[4]) if len(argv) > 4 else 0.0
    srv = listen(port)
    write(record + ".ready", "ready\n")
    conn, _ = srv.accept()
    request = read_request(conn)
    if mode == "silent":
        silent(conn, seconds, record)
    elif mode == "stream":
        stream(conn)
    elif mode == "record":
        write(record, request.decode("latin-1"))
        conn.sendall(b"HTTP/1.1 200 OK\r\ncontent-length: 2\r\n\r\nok")
    time.sleep(0.2)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
