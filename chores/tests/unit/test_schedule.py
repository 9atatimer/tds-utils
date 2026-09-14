"""Behaviors of the cron Schedule value and the due policy (CHORES.DESIGN.md,
Subsystem 2, Key Decisions "Cron evaluation")."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from chores.domain.schedule import (
    DueVerdict,
    InvalidSchedule,
    Schedule,
    due_policy,
)

T0 = datetime(2026, 3, 2, 10, 0)  # a Monday, naive local wall clock


# --- parsing -----------------------------------------------------------------


@pytest.mark.parametrize(
    "expr",
    [
        "* * * * *",
        "0 3 * * *",
        "*/15 9-17 * * 1-5",
        "0 16 * * MON",
        "13 18 1,15 JAN,jul *",
    ],
)
def test_parse_accepts_vixie_syntax(expr: str) -> None:
    """Given a valid 5-field expression, When parsed, Then it round-trips."""
    assert Schedule.parse(expr).expression == expr


@pytest.mark.parametrize(
    "expr",
    [
        "",
        "* * * *",
        "60 * * * *",
        "* 24 * * *",
        "* * 0 * *",
        "* * * 13 *",
        "* * * * 8",
        "a * * * *",
        "*/0 * * * *",
        "5-1 * * * *",
        "@daily",
        "* * * * * *",
    ],
)
def test_parse_rejects_bad_expressions(expr: str) -> None:
    """Given an invalid expression, When parsed, Then InvalidSchedule names it."""
    with pytest.raises(InvalidSchedule) as exc:
        Schedule.parse(expr)
    assert expr in str(exc.value) or "field" in str(exc.value)


# --- matching ----------------------------------------------------------------


def test_matches_exact_minute_hour() -> None:
    """Given `0 3 * * *`, When asked about 03:00 and 03:01, Then only 03:00 matches."""
    s = Schedule.parse("0 3 * * *")
    assert s.matches(datetime(2026, 3, 2, 3, 0))
    assert not s.matches(datetime(2026, 3, 2, 3, 1))


def test_day_of_week_names_and_sunday_as_seven() -> None:
    """Given `0 16 * * 1` and `... * 7`, When matched, Then Monday and Sunday match."""
    assert Schedule.parse("0 16 * * MON").matches(datetime(2026, 3, 2, 16, 0))
    assert Schedule.parse("0 16 * * 7").matches(datetime(2026, 3, 1, 16, 0))
    assert Schedule.parse("0 16 * * 0").matches(datetime(2026, 3, 1, 16, 0))


def test_dom_and_dow_both_restricted_is_or() -> None:
    """Given `0 0 15 * MON`, When the 15th is not a Monday, Then it still matches
    (Vixie semantics: either restricted day field satisfies)."""
    s = Schedule.parse("0 0 15 * MON")
    assert s.matches(datetime(2026, 3, 15, 0, 0))  # a Sunday
    assert s.matches(datetime(2026, 3, 2, 0, 0))  # Monday the 2nd
    assert not s.matches(datetime(2026, 3, 3, 0, 0))


def test_step_and_range() -> None:
    """Given `*/15 9-17 * * *`, When matched, Then quarter hours in 09-17 match."""
    s = Schedule.parse("*/15 9-17 * * *")
    assert s.matches(datetime(2026, 3, 2, 9, 45))
    assert not s.matches(datetime(2026, 3, 2, 18, 0))
    assert not s.matches(datetime(2026, 3, 2, 9, 10))


# --- next_after / slots ------------------------------------------------------


def test_next_after_skips_to_the_following_day() -> None:
    """Given `0 3 * * *` at 10:00, When next_after, Then 03:00 tomorrow."""
    assert Schedule.parse("0 3 * * *").next_after(T0) == datetime(2026, 3, 3, 3, 0)


def test_next_after_is_strictly_after() -> None:
    """Given a time that itself matches, When next_after, Then the next slot, not it."""
    at = datetime(2026, 3, 2, 3, 0)
    assert Schedule.parse("0 3 * * *").next_after(at) == datetime(2026, 3, 3, 3, 0)


def test_slots_between_is_exclusive_start_inclusive_end() -> None:
    """Given hourly, When slots between 10:00 and 13:00, Then 11, 12, 13."""
    s = Schedule.parse("0 * * * *")
    got = s.slots_between(T0, T0 + timedelta(hours=3))
    assert got == [T0 + timedelta(hours=h) for h in (1, 2, 3)]


def test_feb_29_only_in_leap_years() -> None:
    """Given `0 0 29 2 *` in 2026, When next_after, Then 2028-02-29."""
    assert Schedule.parse("0 0 29 2 *").next_after(T0) == datetime(2028, 2, 29, 0, 0)


@settings(max_examples=150, deadline=None)
@given(
    minute=st.integers(0, 59),
    hour=st.integers(0, 23),
    dow=st.integers(0, 6),
    start=st.datetimes(min_value=datetime(2024, 1, 1), max_value=datetime(2030, 1, 1)),
)
def test_next_after_always_matches_and_is_after(
    minute: int, hour: int, dow: int, start: datetime
) -> None:
    """Property: next_after(t) > t and matches(next_after(t))."""
    s = Schedule.parse(f"{minute} {hour} * * {dow}")
    nxt = s.next_after(start)
    assert nxt > start.replace(second=0, microsecond=0)
    assert s.matches(nxt)
    assert s.next_after(nxt) > nxt


# --- due policy --------------------------------------------------------------

GRACE = timedelta(minutes=2)


def test_not_due_when_no_slot_in_window() -> None:
    """Given daily at 03:00 and a 10:00-10:01 window, Then NOT_DUE."""
    v = due_policy(
        Schedule.parse("0 3 * * *"),
        window_start=T0,
        now=T0 + timedelta(minutes=1),
        grace=GRACE,
    )
    assert v == DueVerdict(fire=None, missed=0)


def test_fires_slot_inside_grace() -> None:
    """Given hourly, window 10:00 -> 11:01, Then 11:00 fires, nothing missed."""
    v = due_policy(
        Schedule.parse("0 * * * *"),
        window_start=T0,
        now=T0 + timedelta(hours=1, minutes=1),
        grace=GRACE,
    )
    assert v == DueVerdict(fire=T0 + timedelta(hours=1), missed=0)


def test_slots_older_than_grace_are_missed_not_fired() -> None:
    """Given hourly, asleep 10:00 -> 14:30, Then 11-14 are missed, nothing fires."""
    v = due_policy(
        Schedule.parse("0 * * * *"),
        window_start=T0,
        now=T0 + timedelta(hours=4, minutes=30),
        grace=GRACE,
    )
    assert v == DueVerdict(fire=None, missed=4)


def test_recent_slot_fires_and_older_ones_are_missed() -> None:
    """Given hourly, window 10:00 -> 13:01, Then 13:00 fires and 11, 12 are missed."""
    v = due_policy(
        Schedule.parse("0 * * * *"),
        window_start=T0,
        now=T0 + timedelta(hours=3, minutes=1),
        grace=GRACE,
    )
    assert v == DueVerdict(fire=T0 + timedelta(hours=3), missed=2)


def test_catch_up_fires_one_run_for_the_missed_set() -> None:
    """Given catch_up and only stale slots, Then one run fires for the latest slot
    and the count is still reported."""
    v = due_policy(
        Schedule.parse("0 * * * *"),
        window_start=T0,
        now=T0 + timedelta(hours=4, minutes=30),
        grace=GRACE,
        catch_up=True,
    )
    assert v == DueVerdict(fire=T0 + timedelta(hours=4), missed=4, caught_up=True)
