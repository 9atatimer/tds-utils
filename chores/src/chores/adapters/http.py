"""The HTTP transport seam the completion adapters share, and its urllib
realisation. Keeping it separate lets the adapters be tested with a fake
transport and keeps the one network mechanism in one file."""

from __future__ import annotations

import http.client
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from chores.domain.errors import InfrastructureError


class TransportError(InfrastructureError):
    """Could not reach the server at all."""


class TransportTimeout(InfrastructureError):
    """The server did not answer in time."""


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    body: Mapping[str, object]


class HttpTransport(Protocol):
    def post_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        body: Mapping[str, object],
        timeout_sec: float,
    ) -> HttpResponse: ...


class UrllibTransport:
    def post_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        body: Mapping[str, object],
        timeout_sec: float,
    ) -> HttpResponse:
        data = json.dumps(dict(body)).encode("utf-8")
        try:
            request = urllib.request.Request(  # raises ValueError on a bad url
                url,
                data=data,
                method="POST",
                headers={"Content-Type": "application/json", **headers},
            )
            with urllib.request.urlopen(request, timeout=timeout_sec) as resp:
                return HttpResponse(resp.status, _parse(resp.read()))
        except (ValueError, http.client.HTTPException) as e:
            # unknown url type (ValueError) or InvalidURL, a non-numeric
            # port, which http.client raises as its own HTTPException
            raise TransportError(f"malformed url {url!r}: {e}") from e
        except urllib.error.HTTPError as e:
            return HttpResponse(e.code, _parse(e.read()))
        except TimeoutError as e:
            raise TransportTimeout(str(e)) from e
        except (urllib.error.URLError, OSError) as e:
            reason = getattr(e, "reason", e)
            if isinstance(reason, socket.timeout | TimeoutError):
                raise TransportTimeout(str(reason)) from e
            raise TransportError(str(reason)) from e


def _parse(raw: bytes) -> Mapping[str, object]:
    try:
        parsed = json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"raw": raw[:512].decode("utf-8", "replace")}
    return parsed if isinstance(parsed, dict) else {"raw": parsed}


def probe(url: str, *, timeout_sec: float) -> bool:
    """Can a TCP connection be opened to the host in ``url``? (NetworkPort)"""
    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname
        port = parsed.port  # raises ValueError on a non-numeric port
    except ValueError:
        return False
    if host is None:
        return False
    port = port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout_sec):
            return True
    except OSError:
        return False
