"""RecordsPort's contract, written once and run against every adapter.

The scenario every adapter is built over: the base holds a design record
with one behavior, the working tree adds a second, and the staged index
holds no record at all. The radar likewise: the base's names two entries,
the working tree's a third, and the staged index holds none. A subclass
supplies `port`, a RecordsPort over that scenario whose clock is frozen at
NOW.
"""

from __future__ import annotations

from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import Declaration, parse_declaration
from adherence.domain.records import DesignRecords, Radar, RecordsUnavailable, Ring
from adherence.domain.target import Base, Head
from adherence.ports.records import RecordsPort

BASE = Base("0" * 40)
DESIGN = "docs/design/DESIGN.TOOL.md"
ARCHITECTURE = "docs/design/ARCHITECTURE.TOOL.md"
DECLARATION = (
    b'[layers]\ndomain = ["src/**"]\n'
    b'[records]\ndesign = "docs/design/DESIGN.TOOL.md"\n'
    b'architecture = "docs/design/ARCHITECTURE.TOOL.md"\n'
    b'[radar]\npath = "docs/TECH_RADAR.md"\n'
)
RADAR = "docs/TECH_RADAR.md"
CLOSED = "An order is closed"
REOPENED = "An order is reopened"
# What each target's records state: the behaviors' names, in order.
BEHAVIORS: dict[Base | Head, tuple[str, ...]] = {
    BASE: (CLOSED,),
    Head.working_tree(): (CLOSED, REOPENED),
}
# What each target's radar states: each entry's name and ring, in order.
RADARS: dict[Base | Head, tuple[tuple[str, Ring], ...]] = {
    BASE: (("Python 3", Ring.ADOPT), ("grimp", Ring.TRIAL)),
    Head.working_tree(): (
        ("Python 3", Ring.ADOPT),
        ("grimp", Ring.TRIAL),
        ("pickle", Ring.HOLD),
    ),
}
NOW = 1e9


def declaration() -> Declaration:
    parsed = parse_declaration(DECLARATION)
    assert isinstance(parsed, Declaration), parsed
    return parsed


class RecordsContract:
    def port(self) -> RecordsPort:
        raise NotImplementedError("a contract subclass supplies its adapter")

    def test_records_at_each_target_are_its_own(self) -> None:
        """Given a record that gains a behavior in the working tree, When the
        records are read at the base and at the working tree, Then each
        target answers with its own behaviors."""
        port = self.port()

        for at, names in BEHAVIORS.items():
            records = port.records(at, declaration(), None)
            assert isinstance(records, DesignRecords), records
            assert tuple(b.name for b in records.behaviors) == names

    def test_records_at_a_target_without_them_are_unavailable(self) -> None:
        """Given a target that holds no record, When the records are read
        there, Then the answer is RecordsUnavailable, never empty records."""
        answer = self.port().records(Head.staged_index(), declaration(), None)

        assert isinstance(answer, RecordsUnavailable)
        assert answer.reason

    def test_records_past_the_deadline_time_out(self) -> None:
        """Given a deadline already passed, When the records are read, Then
        the answer is TimedOut, not records."""
        answer = self.port().records(BASE, declaration(), Deadline(epoch_seconds=NOW))

        assert isinstance(answer, TimedOut)

    def test_radar_at_each_target_is_its_own(self) -> None:
        """Given a radar that gains an entry in the working tree, When the
        radar is read at the base and at the working tree, Then each target
        answers with its own entries and their rings."""
        port = self.port()

        for at, entries in RADARS.items():
            radar = port.radar(at, declaration(), None)
            assert isinstance(radar, Radar), radar
            assert tuple((e.name, e.ring) for e in radar.entries) == entries
            assert all(e.path == RADAR and e.line > 0 for e in radar.entries)

    def test_radar_at_a_target_without_one_is_unavailable(self) -> None:
        """Given a target that holds no radar, When the radar is read there,
        Then the answer is RecordsUnavailable, never an empty radar."""
        answer = self.port().radar(Head.staged_index(), declaration(), None)

        assert isinstance(answer, RecordsUnavailable)
        assert answer.reason

    def test_radar_past_the_deadline_times_out(self) -> None:
        """Given a deadline already passed, When the radar is read, Then the
        answer is TimedOut, not a radar."""
        answer = self.port().radar(BASE, declaration(), Deadline(epoch_seconds=NOW))

        assert isinstance(answer, TimedOut)
