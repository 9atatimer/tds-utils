"""Numeric fields at the provider boundary: a malformed token count or cost
in an otherwise successful response is a BackendError (which the runner maps
to FAILED), never a ValueError escaping into the runner."""

from __future__ import annotations

from chores.ports.errors import BackendError


def int_field(value: object, *, provider: str, field: str, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(str(value))
    except ValueError as e:
        raise BackendError(f"{provider}: {field} is not an integer: {value!r}") from e


def float_field(value: object, *, provider: str, field: str) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value))
    except ValueError as e:
        raise BackendError(f"{provider}: {field} is not a number: {value!r}") from e
