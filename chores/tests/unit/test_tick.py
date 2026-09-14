"""The tick use case (CHORES.DESIGN.md Subsystem 2) against fakes."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path

from chores.adapters.definitions import DefinitionsLoader
from chores.application.paths import Paths
from chores.application.tick import TickDeps, tick
from chores.domain.kinds import Kind
from chores.domain.run import RunRecord, RunStatus
from chores.ports.store import TickMark

from ._fakes import (
    FakeClock,
    FakeNetwork,
    FakeNotifier,
    FakePower,
    FakeProcess,
    FakeRunStore,
)
from .test_runner import COMMAND, FakeCatalog, write_home

T0 = datetime(2026, 3, 2, 10, 0, 30)  # local; a tick 30s past the hour
OFFSET = timedelta(hours=-7)  # local = utc - 7h  (so utc = local + 7h)
HOURLY = (
    "---\nname: hourly\nschedule: '0 * * * *'\nkind: command\ncommand: ['true']\n---\n"
)
DEFER = (
    "---\nname: night\nschedule: '0 * * * *'\nkind: command\ncommand: ['true']\n"
    "defer_on_battery: true\n---\n"
)
CATCH = (
    "---\nname: catch\nschedule: '0 * * * *'\nkind: command\ncommand: ['true']\n"
    "catch_up: true\n---\n"
)


class Harness:
    def __init__(
        self, tmp_path: Path, *, chores: Mapping[str, str], config: str = ""
    ) -> None:
        home = tmp_path / "home"
        write_home(home, chores=chores, config=config)
        self.store = FakeRunStore()
        self.clock = FakeClock(T0, utc_offset=OFFSET)
        self.process = FakeProcess()
        self.power = FakePower()
        self.network = FakeNetwork()
        self.notifier = FakeNotifier()
        self.launched: list[str] = []
        self.definitions = DefinitionsLoader(home, revision_reader=lambda _: "rev1")
        self.paths = Paths(str(home), str(tmp_path / "state"), str(tmp_path / "data"))
        # a previous tick one interval ago, so the window has a start
        self.store.mark_tick(
            TickMark(at=self.clock.now_utc() - timedelta(seconds=60), ledger_rows=0)
        )

    def deps(self) -> TickDeps:
        return TickDeps(
            definitions=self.definitions,
            catalog_for=lambda d: FakeCatalog(),
            store=self.store,
            clock=self.clock,
            process=self.process,
            power=self.power,
            network=self.network,
            notifier=self.notifier,
            paths=self.paths,
            launch=self.launched.append,
            run_id_suffix=lambda: "t1",
        )

    def statuses(self, chore: str) -> list[RunStatus]:
        return [r.status for r in reversed(self.store.records(chore=chore))]


def test_due_slot_launches_a_run_and_marks_the_tick(tmp_path: Path) -> None:
    """Given hourly and a tick 30s past the hour, Then the run is launched once."""
    h = Harness(tmp_path, chores={"hourly": HOURLY})
    report = tick(h.deps())
    assert h.launched == ["hourly"] and report.fired == ["hourly"]
    mark = h.store.last_tick()
    assert mark and mark.at == h.clock.now_utc() and mark.ledger_rows == 0


def test_not_due_launches_nothing(tmp_path: Path) -> None:
    h = Harness(tmp_path, chores={"hourly": HOURLY})
    h.clock.advance(120)
    h.store.mark_tick(
        TickMark(at=h.clock.now_utc() - timedelta(seconds=60), ledger_rows=0)
    )
    assert tick(h.deps()).fired == [] and h.launched == []


def test_a_consumed_slot_is_not_fired_again_next_tick(tmp_path: Path) -> None:
    """Given the run's PENDING record exists, When the next tick comes, Then nothing."""
    h = Harness(tmp_path, chores={"hourly": HOURLY})
    tick(h.deps())
    h.store.write_record(
        RunRecord.pending(
            run_id="hourly-x",
            chore="hourly",
            kind=Kind.COMMAND,
            definition_rev="r",
            started=h.clock.now_utc(),
        )
    )
    h.clock.advance(60)
    assert tick(h.deps()).fired == []


def test_sleep_gap_records_missed_and_fires_the_recent_slot(tmp_path: Path) -> None:
    """Given the last tick at 08:00 and now 12:00:30, Then 9-11 MISSED and 12 fires."""
    h = Harness(tmp_path, chores={"hourly": HOURLY})
    h.store.mark_tick(
        TickMark(at=h.clock.now_utc() - timedelta(hours=2), ledger_rows=0)
    )
    h.clock.advance(2 * 3600)  # now 12:00:30
    report = tick(h.deps())
    assert report.fired == ["hourly"]
    missed = [
        r for r in h.store.records(chore="hourly") if r.status is RunStatus.MISSED
    ]
    assert len(missed) == 1 and "3" in (missed[0].reason or "")
    assert h.store.ledger_rows()[0]["status"] == "MISSED"


def test_stale_slots_only_are_missed_not_fired_unless_catch_up(tmp_path: Path) -> None:
    h = Harness(tmp_path, chores={"hourly": HOURLY, "catch": CATCH})
    h.store.mark_tick(
        TickMark(at=h.clock.now_utc() - timedelta(hours=3), ledger_rows=0)
    )
    h.clock.advance(30 * 60)  # 10:30:30 -> slots 08,09,10 all older than grace
    report = tick(h.deps())
    assert report.fired == ["catch"] and h.launched == ["catch"]
    assert h.statuses("hourly") == [RunStatus.MISSED]
    assert h.statuses("catch") == [RunStatus.MISSED]


def test_paused_writes_skipped_paused_and_no_launch(tmp_path: Path) -> None:
    h = Harness(tmp_path, chores={"hourly": HOURLY})
    h.store.pause("flight")
    tick(h.deps())
    assert h.launched == [] and h.statuses("hourly") == [RunStatus.SKIPPED_PAUSED]


def test_defer_on_battery_retains_the_slot_once_and_fires_on_ac(tmp_path: Path) -> None:
    h = Harness(tmp_path, chores={"night": DEFER})
    h.power.battery = True
    tick(h.deps())
    h.clock.advance(60)
    tick(h.deps())
    assert h.statuses("night") == [RunStatus.DEFERRED_BATTERY] and h.launched == []
    h.power.battery = False
    h.clock.advance(60)
    assert tick(h.deps()).fired == ["night"] and h.launched == ["night"]


def test_dead_running_and_stale_pending_become_interrupted(tmp_path: Path) -> None:
    h = Harness(tmp_path, chores={"hourly": HOURLY})
    dead = RunRecord.pending(
        run_id="hourly-a",
        chore="hourly",
        kind=Kind.COMMAND,
        definition_rev="r",
        started=h.clock.now_utc() - timedelta(minutes=5),
    ).start(pid=9, pgid=9, process_start=1.0)
    stale = RunRecord.pending(
        run_id="hourly-b",
        chore="hourly",
        kind=Kind.COMMAND,
        definition_rev="r",
        started=h.clock.now_utc() - timedelta(minutes=5),
    )
    fresh = RunRecord.pending(
        run_id="hourly-c",
        chore="hourly",
        kind=Kind.COMMAND,
        definition_rev="r",
        started=h.clock.now_utc() - timedelta(seconds=10),
    )
    for r in (dead, stale, fresh):
        h.store.write_record(r)
    tick(h.deps())
    got = {r.run_id: r.status for r in h.store.records(chore="hourly")}
    assert (
        got["hourly-a"] is RunStatus.INTERRUPTED
        and got["hourly-b"] is RunStatus.INTERRUPTED
    )
    assert got["hourly-c"] is RunStatus.PENDING
    assert (
        sum(1 for row in h.store.ledger_rows() if row["status"] == "INTERRUPTED") == 2
    )
    assert sum(1 for n in h.store.notifications() if "INTERRUPTED" in n.text) == 2
    assert h.launched == []  # the fresh PENDING consumed the 10:00 slot


def test_live_running_skips_overlap(tmp_path: Path) -> None:
    h = Harness(tmp_path, chores={"hourly": HOURLY})
    live = RunRecord.pending(
        run_id="hourly-a",
        chore="hourly",
        kind=Kind.COMMAND,
        definition_rev="r",
        started=h.clock.now_utc() - timedelta(hours=1),
    ).start(pid=9, pgid=9, process_start=1.0)
    h.store.write_record(live)
    h.process.alive_pids.add(9)
    tick(h.deps())
    assert h.launched == [] and h.statuses("hourly")[-1] is RunStatus.SKIPPED_OVERLAP


def test_invalid_definition_is_recorded_once_and_notified(tmp_path: Path) -> None:
    h = Harness(tmp_path, chores={"bad": "---\nname: bad\nkind: prompt\n---\n"})
    tick(h.deps())
    h.clock.advance(60)
    tick(h.deps())
    assert h.statuses("bad") == [RunStatus.INVALID]
    assert sum(1 for n in h.store.notifications() if "INVALID" in n.text) == 1


def test_disabled_chore_writes_nothing(tmp_path: Path) -> None:
    h = Harness(
        tmp_path,
        chores={
            "dormant": HOURLY.replace("name: hourly", "name: dormant\nenabled: false")
        },
    )
    tick(h.deps())
    assert h.store.records() == [] and h.launched == []


def test_ledger_shrink_is_reported(tmp_path: Path) -> None:
    h = Harness(
        tmp_path, chores={"tidy": COMMAND.replace("'* * * * *'", "'0 3 * * *'")}
    )
    h.store.mark_tick(
        TickMark(at=h.clock.now_utc() - timedelta(seconds=60), ledger_rows=7)
    )
    report = tick(h.deps())
    assert any("shrank" in w for w in report.warnings)
    assert any("shrank" in n.text for n in h.store.notifications())


def test_second_concurrent_tick_is_a_noop(tmp_path: Path) -> None:
    h = Harness(tmp_path, chores={"hourly": HOURLY})
    h.store.lock_held = True
    assert tick(h.deps()).locked_out is True and h.launched == []
