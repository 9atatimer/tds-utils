"""Budgets, usage and the spend policy (CHORES.DESIGN.md Subsystem 5).

Dimensions are tokens, USD, turns and seconds. A budget declares any subset
(seconds always); a ceiling is the same shape over a rolling window. Both
are plain values with one invariant each: nothing negative, seconds > 0.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from chores.domain.errors import DomainError


class InvalidBudget(DomainError):
    """A budget or ceiling carried a negative or zero-length dimension."""


# --- helpers -----------------------------------------------------------------


def _require_non_negative(name: str, value: int | float | None) -> None:
    if value is not None and value < 0:
        raise InvalidBudget(f"{name} may not be negative (got {value})")


# --- values ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Budget:
    """What one run may consume. ``seconds`` is the wall-clock timeout."""

    seconds: int
    tokens: int | None = None
    usd: float | None = None
    turns: int | None = None

    def __post_init__(self) -> None:
        if self.seconds <= 0:
            raise InvalidBudget(f"seconds must be positive (got {self.seconds})")
        for name in ("tokens", "usd", "turns"):
            _require_non_negative(name, getattr(self, name))

    def declared_dimensions(self) -> frozenset[str]:
        """The names of the dimensions this budget bounds (never ``seconds``)."""
        return frozenset(
            name
            for name in ("tokens", "usd", "turns")
            if getattr(self, name) is not None
        )


@dataclass(frozen=True, slots=True)
class Ceiling:
    """A rolling-window cap in any subset of tokens, USD and turns."""

    tokens: int | None = None
    usd: float | None = None
    turns: int | None = None

    def __post_init__(self) -> None:
        for name in ("tokens", "usd", "turns"):
            _require_non_negative(name, getattr(self, name))

    def dimensions(self) -> frozenset[str]:
        """The names of the dimensions this ceiling caps."""
        return frozenset(
            name
            for name in ("tokens", "usd", "turns")
            if getattr(self, name) is not None
        )


@dataclass(frozen=True, slots=True)
class Usage:
    """What a run (or a sum of runs) consumed. ``None`` means unmeasured."""

    tokens_in: int
    tokens_out: int
    seconds: float
    usd: float | None = None
    turns: int | None = None
    cpu_seconds: float = 0.0
    disk_bytes: int = 0

    @property
    def tokens(self) -> int:
        return self.tokens_in + self.tokens_out

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            tokens_in=self.tokens_in + other.tokens_in,
            tokens_out=self.tokens_out + other.tokens_out,
            seconds=self.seconds + other.seconds,
            usd=_add_optional(self.usd, other.usd),
            turns=_add_optional_int(self.turns, other.turns),
            cpu_seconds=self.cpu_seconds + other.cpu_seconds,
            disk_bytes=self.disk_bytes + other.disk_bytes,
        )


def _add_optional(a: float | None, b: float | None) -> float | None:
    if a is None:
        return b
    if b is None:
        return a
    return a + b


def _add_optional_int(a: int | None, b: int | None) -> int | None:
    if a is None:
        return b
    if b is None:
        return a
    return a + b


# --- the policy --------------------------------------------------------------


class SpendAction(Enum):
    CONTINUE = "continue"
    STOP = "stop"


@dataclass(frozen=True, slots=True)
class SpendVerdict:
    action: SpendAction
    reason: str | None = None


def spend_policy(usage: Usage, budget: Budget) -> SpendVerdict:
    """STOP when usage exceeds any declared dimension of the budget."""
    if budget.tokens is not None and usage.tokens > budget.tokens:
        return SpendVerdict(
            SpendAction.STOP, f"tokens {usage.tokens} > budget {budget.tokens}"
        )
    if budget.usd is not None and usage.usd is not None and usage.usd > budget.usd:
        return SpendVerdict(
            SpendAction.STOP, f"usd {usage.usd:.4f} > budget {budget.usd:.4f}"
        )
    if (
        budget.turns is not None
        and usage.turns is not None
        and usage.turns > budget.turns
    ):
        return SpendVerdict(
            SpendAction.STOP, f"turns {usage.turns} > budget {budget.turns}"
        )
    if usage.seconds > budget.seconds:
        return SpendVerdict(
            SpendAction.STOP, f"seconds {usage.seconds:.0f} > budget {budget.seconds}"
        )
    return SpendVerdict(SpendAction.CONTINUE)
