"""Budget, Usage and spend_policy (CHORES.DESIGN.md Subsystem 5)."""

from __future__ import annotations

import pytest

from chores.domain.budget import (
    Budget,
    Ceiling,
    SpendAction,
    Usage,
    spend_policy,
)
from chores.domain.errors import DomainError


def test_budget_rejects_negative_and_zero_seconds() -> None:
    """Given a negative token budget or zero seconds, Then construction fails."""
    with pytest.raises(DomainError):
        Budget(tokens=-1, seconds=60)
    with pytest.raises(DomainError):
        Budget(seconds=0)


def test_usage_sums_dimension_wise_with_none_as_absent() -> None:
    """Given two usages, When added, Then counts add and absent USD stays absent."""
    a = Usage(tokens_in=10, tokens_out=5, usd=0.5, turns=2, seconds=1.0)
    b = Usage(tokens_in=1, tokens_out=1, usd=None, turns=None, seconds=2.0)
    total = a + b
    assert total.tokens == 17
    assert total.usd == 0.5
    assert total.turns == 2
    assert total.seconds == 3.0


def test_spend_continues_under_budget() -> None:
    """Given usage under every declared dimension, Then CONTINUE."""
    v = spend_policy(
        Usage(tokens_in=100, tokens_out=100, usd=0.10, turns=3, seconds=5),
        Budget(tokens=1000, usd=1.0, turns=10, seconds=60),
    )
    assert v.action is SpendAction.CONTINUE and v.reason is None


@pytest.mark.parametrize(
    ("usage", "budget", "word"),
    [
        (
            Usage(tokens_in=600, tokens_out=500, seconds=1),
            Budget(tokens=1000, seconds=60),
            "tokens",
        ),
        (
            Usage(tokens_in=0, tokens_out=0, usd=2.0, seconds=1),
            Budget(usd=1.0, seconds=60),
            "usd",
        ),
        (
            Usage(tokens_in=0, tokens_out=0, turns=11, seconds=1),
            Budget(turns=10, seconds=60),
            "turns",
        ),
        (Usage(tokens_in=0, tokens_out=0, seconds=61), Budget(seconds=60), "seconds"),
    ],
)
def test_spend_stops_when_any_declared_dimension_is_exceeded(
    usage: Usage, budget: Budget, word: str
) -> None:
    """Given usage over one declared dimension, Then STOP names that dimension."""
    v = spend_policy(usage, budget)
    assert v.action is SpendAction.STOP
    assert v.reason is not None and word in v.reason


def test_spend_ignores_undeclared_dimensions() -> None:
    """Given no USD budget, When USD usage is large, Then CONTINUE."""
    v = spend_policy(
        Usage(tokens_in=0, tokens_out=0, usd=99.0, seconds=1), Budget(seconds=60)
    )
    assert v.action is SpendAction.CONTINUE


def test_ceiling_rejects_negative() -> None:
    """Given a negative ceiling, Then construction fails."""
    with pytest.raises(DomainError):
        Ceiling(usd=-1.0)
