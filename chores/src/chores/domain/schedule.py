"""The cron Schedule value and the due policy.

A Schedule is a 5-field Vixie cron expression evaluated on the local wall
clock, so every datetime here is naive local time (CHORES.DESIGN.md,
Subsystem 2: a spring-forward slot fires once at the first instant after the
gap, a fall-back slot fires once, keyed by its wall-clock label -- both fall
out of evaluating naive datetimes). The domain owns this matcher so the
schedule stays a pure value with no library at the core (Key Decisions,
"Cron evaluation"; croniter is a Rejection).

Supported syntax per field: ``*``, ``n``, ``a-b``, ``*/s``, ``a-b/s``, comma
lists, and names for months (JAN..DEC) and weekdays (SUN..SAT). Day-of-week
accepts 0-7 with both 0 and 7 meaning Sunday. When day-of-month and
day-of-week are both restricted, either satisfies (Vixie semantics).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from chores.domain.errors import DomainError

# --- constants ---------------------------------------------------------------

_MONTH_NAMES = {
    name: i + 1
    for i, name in enumerate(
        [
            "jan",
            "feb",
            "mar",
            "apr",
            "may",
            "jun",
            "jul",
            "aug",
            "sep",
            "oct",
            "nov",
            "dec",
        ]
    )
}
_DOW_NAMES = {
    name: i for i, name in enumerate(["sun", "mon", "tue", "wed", "thu", "fri", "sat"])
}
_FIELD_SPECS: tuple[tuple[str, int, int, dict[str, int]], ...] = (
    ("minute", 0, 59, {}),
    ("hour", 0, 23, {}),
    ("day-of-month", 1, 31, {}),
    ("month", 1, 12, _MONTH_NAMES),
    ("day-of-week", 0, 7, _DOW_NAMES),
)
_SEARCH_HORIZON = timedelta(days=366 * 5)


class InvalidSchedule(DomainError):
    """The expression is not a 5-field cron expression this domain accepts."""


# --- predicates --------------------------------------------------------------


def _is_wildcard(token: str) -> bool:
    return token == "*"


# --- helpers -----------------------------------------------------------------


def _parse_atom(
    atom: str, *, low: int, high: int, names: dict[str, int], field: str
) -> int:
    key = atom.lower()
    if key in names:
        return names[key]
    if not atom.isdigit():
        raise InvalidSchedule(f"{field} field: '{atom}' is not a number or name")
    value = int(atom)
    if value < low or value > high:
        raise InvalidSchedule(f"{field} field: {value} is outside {low}-{high}")
    return value


def _parse_field(
    text: str, *, field: str, low: int, high: int, names: dict[str, int]
) -> frozenset[int]:
    """Expand one cron field into the set of integers it admits."""
    values: set[int] = set()
    for part in text.split(","):
        body, _, step_text = part.partition("/")
        step = 1
        if step_text:
            if not step_text.isdigit() or int(step_text) < 1:
                raise InvalidSchedule(f"{field} field: bad step '/{step_text}'")
            step = int(step_text)
        if _is_wildcard(body):
            start, end = low, high
        elif "-" in body:
            a, _, b = body.partition("-")
            start = _parse_atom(a, low=low, high=high, names=names, field=field)
            end = _parse_atom(b, low=low, high=high, names=names, field=field)
            if start > end:
                raise InvalidSchedule(f"{field} field: range '{body}' runs backwards")
        else:
            start = _parse_atom(body, low=low, high=high, names=names, field=field)
            end = high if step_text else start
        values.update(range(start, end + 1, step))
    return frozenset(values)


def _floor_minute(at: datetime) -> datetime:
    return at.replace(second=0, microsecond=0)


# --- the value ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Schedule:
    """A parsed 5-field cron expression. Construct through :meth:`parse`."""

    expression: str
    minutes: frozenset[int]
    hours: frozenset[int]
    days_of_month: frozenset[int]
    months: frozenset[int]
    days_of_week: frozenset[int]
    dom_restricted: bool
    dow_restricted: bool

    @classmethod
    def parse(cls, expression: str) -> Schedule:
        """Parse ``expression`` or raise :class:`InvalidSchedule`."""
        fields = expression.split()
        if len(fields) != 5:
            raise InvalidSchedule(
                f"'{expression}': expected 5 fields "
                f"(minute hour day month weekday), got {len(fields)}"
            )
        parsed: list[frozenset[int]] = []
        for text, (name, low, high, names) in zip(fields, _FIELD_SPECS, strict=True):
            parsed.append(
                _parse_field(text, field=name, low=low, high=high, names=names)
            )
        minutes, hours, dom, months, dow = parsed
        dow = frozenset(0 if d == 7 else d for d in dow)
        return cls(
            expression=expression,
            minutes=minutes,
            hours=hours,
            days_of_month=dom,
            months=months,
            days_of_week=dow,
            dom_restricted=not _is_wildcard(fields[2].partition("/")[0]),
            dow_restricted=not _is_wildcard(fields[4].partition("/")[0]),
        )

    def _day_matches(self, at: datetime) -> bool:
        dom_ok = at.day in self.days_of_month
        dow_ok = (
            at.weekday() + 1
        ) % 7 in self.days_of_week  # python Monday=0 -> cron Sunday=0
        if self.dom_restricted and self.dow_restricted:
            return dom_ok or dow_ok
        return dom_ok and dow_ok

    def matches(self, at: datetime) -> bool:
        """Is the minute containing ``at`` a slot of this schedule?"""
        return (
            at.minute in self.minutes
            and at.hour in self.hours
            and at.month in self.months
            and self._day_matches(at)
        )

    def next_after(self, at: datetime) -> datetime:
        """The first slot strictly after the minute containing ``at``."""
        candidate = _floor_minute(at) + timedelta(minutes=1)
        horizon = candidate + _SEARCH_HORIZON
        while candidate < horizon:
            if candidate.month not in self.months or not self._day_matches(candidate):
                candidate = (candidate + timedelta(days=1)).replace(hour=0, minute=0)
                continue
            if candidate.hour not in self.hours:
                candidate = (candidate + timedelta(hours=1)).replace(minute=0)
                continue
            if candidate.minute in self.minutes:
                return candidate
            candidate += timedelta(minutes=1)
        raise InvalidSchedule(
            f"'{self.expression}' has no slot within five years of {at}"
        )

    def slots_between(self, start: datetime, end: datetime) -> list[datetime]:
        """Slots in the half-open window (start, end]."""
        slots: list[datetime] = []
        cursor = start
        while True:
            cursor = self.next_after(cursor)
            if cursor > end:
                return slots
            slots.append(cursor)


# --- the policy --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DueVerdict:
    """What tick should do for one chore at one instant."""

    fire: datetime | None
    missed: int
    caught_up: bool = False


def due_policy(
    schedule: Schedule,
    *,
    window_start: datetime,
    now: datetime,
    grace: timedelta,
    catch_up: bool = False,
) -> DueVerdict:
    """Decide FIRE / MISSED / NOT_DUE for the slots in (window_start, now].

    The newest slot fires when it is no older than ``grace``; every older slot
    is missed. With ``catch_up`` a set consisting only of stale slots fires one
    run, attributed to the newest slot, and still reports the count.
    """
    slots = schedule.slots_between(window_start, now)
    if not slots:
        return DueVerdict(fire=None, missed=0)
    newest = slots[-1]
    if now - newest <= grace:
        return DueVerdict(fire=newest, missed=len(slots) - 1)
    if catch_up:
        return DueVerdict(fire=newest, missed=len(slots), caught_up=True)
    return DueVerdict(fire=None, missed=len(slots))
