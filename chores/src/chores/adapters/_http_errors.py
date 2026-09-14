"""Map HTTP outcomes to the typed BackendError family (shared by the HTTP adapters)."""

from __future__ import annotations

from collections.abc import Mapping

from chores.adapters.http import HttpResponse, TransportError, TransportTimeout
from chores.ports.errors import (
    BackendError,
    BackendTimeout,
    ModelNotFound,
    RateLimited,
    Unauthorized,
    Unreachable,
)


def raise_for_transport(error: Exception, *, provider: str) -> BackendError:
    if isinstance(error, TransportTimeout):
        return BackendTimeout(f"{provider}: {error}")
    if isinstance(error, TransportError):
        return Unreachable(f"{provider}: {error}")
    return BackendError(f"{provider}: {error}")


def raise_for_status(response: HttpResponse, *, provider: str) -> None:
    status = response.status
    if 200 <= status < 300:
        return
    detail = _detail(response.body)
    if status in (401, 403):
        raise Unauthorized(f"{provider}: HTTP {status} {detail}")
    if status == 429:
        raise RateLimited(f"{provider}: HTTP 429 {detail}")
    if status == 404 and "model" in detail.lower():
        raise ModelNotFound(f"{provider}: {detail}")
    raise BackendError(f"{provider}: HTTP {status} {detail}")


def _detail(body: Mapping[str, object]) -> str:
    error = body.get("error")
    if isinstance(error, Mapping):
        return str(error.get("message", error))
    if error is not None:
        return str(error)
    return str(body.get("raw", ""))[:200]
