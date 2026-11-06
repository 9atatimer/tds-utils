"""An in-process S3-protocol server that verifies every request's signature.

The warehouse record warns that `s3rver` checks the access key id and
ignores the signature, so it green-lights a client signing with the wrong
secret (template-tools ARCHITECTURE.DATA-WAREHOUSE.md, Topology). This
fake recomputes each request's AWS Signature Version 4 with botocore's
own signer and refuses a request whose signature is missing, malformed or
different, whose payload digest does not match its body, or whose
credential scope names another region. Each credential holds grants --
a method and a key pattern -- so a test can scope one to a repository's
prefixes as the infra module does. It speaks path-style PUT and GET of an
object in one bucket, which is all the warehouse adapter asks.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import TracebackType
from urllib.parse import unquote, urlsplit

from botocore.auth import S3SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials

AUTHORIZATION = re.compile(
    r"AWS4-HMAC-SHA256 Credential=(?P<key>[^/]+)/(?P<date>\d{8})/(?P<region>[^/]+)"
    r"/s3/aws4_request, ?SignedHeaders=(?P<signed>[a-z0-9;-]+),"
    r" ?Signature=(?P<signature>[0-9a-f]{64})"
)
UNSIGNED = "UNSIGNED-PAYLOAD"


@dataclass(frozen=True, slots=True)
class Grant:
    """One method allowed on the keys matching a pattern (`*` spans `/`)."""

    method: str
    pattern: str


@dataclass(frozen=True, slots=True)
class Credential:
    secret: str
    grants: tuple[Grant, ...]


@dataclass(slots=True)
class Ledger:
    """What the server holds and what it refused, and why."""

    objects: dict[str, bytes] = field(default_factory=dict)
    refused: list[str] = field(default_factory=list)


def _xml_error(code: str, message: str) -> bytes:
    return (
        f'<?xml version="1.0" encoding="UTF-8"?><Error><Code>{code}</Code>'
        f"<Message>{message}</Message></Error>"
    ).encode()


# A refused request's status, error code and message.
Refusal = tuple[int, str, str]


def _scope_refusal(
    match: re.Match[str], region: str, headers: Mapping[str, str], body: bytes
) -> Refusal | None:
    """Why the signature's scope, payload digest or signed headers refuse
    the request before its signature is computed."""
    amz_date = headers.get("x-amz-date", "")
    if match["region"] != region or match["date"] != amz_date[:8]:
        return 403, "SignatureDoesNotMatch", "credential scope mismatch"
    payload = headers.get("x-amz-content-sha256", "")
    if payload != UNSIGNED and payload != hashlib.sha256(body).hexdigest():
        return 400, "XAmzContentSHA256Mismatch", "payload digest mismatch"
    signed = match["signed"].split(";")
    if "host" not in signed or any(name not in headers for name in signed):
        return 403, "SignatureDoesNotMatch", "a signed header is absent"
    return None


def _signature_refusal(
    method: str,
    raw_path: str,
    headers: Mapping[str, str],
    body: bytes,
    match: re.Match[str],
    secret: str,
) -> Refusal | None:
    """Why the signature botocore's signer computes is not the request's."""
    signed = match["signed"].split(";")
    request = AWSRequest(
        method=method,
        url=f"http://{headers['host']}{raw_path}",
        data=body,
        headers={name: headers[name] for name in signed},
    )
    request.context["timestamp"] = headers.get("x-amz-date", "")
    signer = S3SigV4Auth(Credentials(match["key"], secret), "s3", match["region"])
    canonical = signer.canonical_request(request)
    expected = signer.signature(signer.string_to_sign(request, canonical), request)
    if not hmac.compare_digest(expected, match["signature"]):
        return 403, "SignatureDoesNotMatch", "signature mismatch"
    return None


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        *,
        bucket: str,
        region: str,
        credentials: Mapping[str, Credential],
        ledger: Ledger,
    ) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.bucket = bucket
        self.region = region
        self.credentials = credentials
        self.ledger = ledger
        self.lock = threading.Lock()

    def refusal(
        self, method: str, raw_path: str, headers: Mapping[str, str], body: bytes
    ) -> Refusal | None:
        """Why the request is refused (status, code, message), or None."""
        match = AUTHORIZATION.fullmatch(headers.get("authorization", ""))
        if match is None:
            return 403, "AccessDenied", "missing or malformed signature"
        credential = self.credentials.get(match["key"])
        if credential is None:
            return 403, "InvalidAccessKeyId", "unknown access key"
        refused = _scope_refusal(match, self.region, headers, body)
        if refused is None:
            refused = _signature_refusal(
                method, raw_path, headers, body, match, credential.secret
            )
        return (
            refused
            if refused is not None
            else self.grant_refusal(method, raw_path, credential)
        )

    def grant_refusal(
        self, method: str, raw_path: str, credential: Credential
    ) -> Refusal | None:
        """Why a signed request falls outside its credential's grants."""
        key = self.key_of(raw_path)
        if key is None or not any(
            g.method == method and fnmatchcase(key, g.pattern)
            for g in credential.grants
        ):
            return 403, "AccessDenied", "outside the credential's grants"
        return None

    def key_of(self, raw_path: str) -> str | None:
        path = unquote(urlsplit(raw_path).path)
        prefix = f"/{self.bucket}/"
        return path[len(prefix) :] if path.startswith(prefix) else None


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: _Server

    def log_message(self, format: str, *args: object) -> None:
        """Quiet: the test asserts on the ledger, not on a log."""

    def _reply(self, status: int, body: bytes = b"") -> None:
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        if status == 200 and self.command == "PUT":
            self.send_header("ETag", f'"{hashlib.md5(body).hexdigest()}"')
        self.end_headers()
        self.wfile.write(body)

    def _handle(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        headers = {k.lower(): v for k, v in self.headers.items()}
        server = self.server
        refused = server.refusal(self.command, self.path, headers, body)
        if refused is not None:
            status, code, message = refused
            with server.lock:
                server.ledger.refused.append(f"{self.command} {self.path}: {message}")
            self._reply(status, _xml_error(code, message))
            return
        key = str(server.key_of(self.path))
        with server.lock:
            if self.command == "PUT":
                server.ledger.objects[key] = body
                self._reply(200)
                return
            held = server.ledger.objects.get(key)
        if held is None:
            self._reply(404, _xml_error("NoSuchKey", "no such key"))
            return
        self._reply(200, held)

    def do_PUT(self) -> None:
        self._handle()

    def do_GET(self) -> None:
        self._handle()


class SigningS3:
    """The fake, serving on a loopback port while the context is open."""

    def __init__(
        self,
        *,
        bucket: str,
        region: str,
        credentials: Mapping[str, Credential],
    ) -> None:
        self.ledger = Ledger()
        self._server = _Server(
            bucket=bucket, region=region, credentials=credentials, ledger=self.ledger
        )
        self._thread = threading.Thread(target=self._server.serve_forever)

    @property
    def endpoint(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host!s}:{port}"

    def __enter__(self) -> SigningS3:
        self._thread.start()
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
