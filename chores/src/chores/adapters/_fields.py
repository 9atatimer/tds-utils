"""Numeric fields at the provider boundary: a malformed, negative or
non-finite token count or cost in an otherwise successful response is a
BackendError (which the runner maps to FAILED), never a ValueError escaping
into the runner and never a NaN reaching the spend policies or the ledger."""

from __future__ import annotations

import math

from chores.ports.errors import BackendError


def int_field(value: object, *, provider: str, field: str, default: int = 0) -> int:
    if value is None:
        return default
    try:
        parsed = int(str(value))
    except ValueError as e:
        raise BackendError(f"{provider}: {field} is not an integer: {value!r}") from e
    if parsed < 0:
        raise BackendError(f"{provider}: {field} is negative: {parsed}")
    return parsed


def float_field(value: object, *, provider: str, field: str) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(str(value))
    except ValueError as e:
        raise BackendError(f"{provider}: {field} is not a number: {value!r}") from e
    if not math.isfinite(parsed) or parsed < 0:
        raise BackendError(f"{provider}: {field} must be finite and >= 0: {parsed}")
    return parsed
