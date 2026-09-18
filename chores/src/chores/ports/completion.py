"""CompletionPort -- the single-turn seam (CHORES.DESIGN.md Subsystem 4)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from chores.domain.run import Billing


@dataclass(frozen=True, slots=True)
class CompletionRequest:
    prompt: str
    model: str
    timeout_sec: int
    max_output_tokens: int | None


@dataclass(frozen=True, slots=True)
class CompletionResponse:
    text: str
    tokens_in: int
    tokens_out: int
    usd: float | None
    provider: str
    model: str
    latency_sec: float
    billing: Billing


class CompletionPort(Protocol):
    def complete(self, request: CompletionRequest) -> CompletionResponse:
        """One response, or a :class:`chores.ports.errors.BackendError`."""
        ...
