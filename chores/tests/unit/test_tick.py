"""The tick use case (CHORES.DESIGN.md Subsystem 2) against fakes."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from chores.adapters.definitions import DefinitionsLoader
from chores.adapters.scheduler import LaunchdInstaller
from chores.application.paths import Paths
from chores.application.run import run_chore
from chores.application.tick import TickDeps, tick
from chores.domain.chore import Chore
from chores.domain.kinds import Kind
from chores.domain.run import RunRecord, RunStatus
from chores.domain.schedule import InvalidSchedule
from chores.ports.store import ARTIFACTS, TickMark

from ._fakes import (
    FakeClock,
    FakeNetwork,
    FakeNotifier,
    FakePower,
    FakeProcess,
    FakeRunStore,
)
from ._harness import COMMAND, PROMPT, FakeCatalog, FullHarness, write_home

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


def test_tick_does_not_overwrite_a_run_that_finished_during_the_scan(
    tmp_path: Path,
) -> None:
    """Given a RUNNING record whose process is gone because the runner already
    wrote SUCCEEDED, Then tick leaves SUCCEEDED alone."""
    h = FullHarness(tmp_path, chores={"tidy": COMMAND})
    stale = RunRecord.pending(
        run_id="tidy-a",
        chore="tidy",
        kind=Kind.COMMAND,
        definition_rev="r",
        started=h.clock.now_utc() - timedelta(minutes=2),
    ).start(pid=9, pgid=9, process_start=1.0)
    h.store.write_record(stale)
    done = stale.finish(RunStatus.SUCCEEDED, ended=h.clock.now_utc(), reason=None)

    class RacingStore(type(h.store)):  # type: ignore[misc]
        pass

    original_records = h.store.records

    def records_then_finish(**kw):  # type: ignore[no-untyped-def]
        out = original_records(**kw)
        h.store.write_record(done)  # the runner finishes right after the scan
        return out

    h.store.records = records_then_finish  # type: ignore[method-assign]
    h.store.mark_tick(
        TickMark(at=h.clock.now_utc() - timedelta(seconds=60), ledger_rows=0)
    )
    tick(h.deps().as_tick_deps())
    assert h.store.read_record("tidy-a").status is RunStatus.SUCCEEDED  # type: ignore[union-attr]
    assert not any(row["status"] == "INTERRUPTED" for row in h.store.ledger_rows())


def test_tick_survives_a_chore_that_raises(tmp_path: Path) -> None:
    """Given a chore whose consideration raises a domain error, Then the tick
    records it INVALID and still marks liveness."""
    h = FullHarness(tmp_path, chores={"tidy": COMMAND})
    h.store.mark_tick(
        TickMark(at=h.clock.now_utc() - timedelta(seconds=60), ledger_rows=0)
    )

    def boom(name: str) -> str | None:
        raise InvalidSchedule("exploded")

    h.store.chore_paused = boom  # type: ignore[method-assign]
    report = tick(h.deps().as_tick_deps())
    assert "tidy" in report.invalid
    assert h.store.last_tick() is not None


def test_tick_interrupt_is_a_check_and_set(tmp_path: Path) -> None:
    """Given a runner that finishes between the tick's scan and its write, Then
    the terminal SUCCEEDED record survives and no INTERRUPTED row is appended."""
    from chores.domain.budget import Usage
    from chores.domain.run import Billing

    h = FullHarness(tmp_path, chores={"brand": PROMPT})
    running = RunRecord.pending(
        run_id="brand-20260302T090000Z-aa",
        chore="brand",
        kind=Kind.PROMPT,
        definition_rev="r",
        started=T0 - timedelta(minutes=5),
    ).start(pid=4242, pgid=4242, process_start=1.0)
    h.store.write_record(running)  # pid 4242 is not in the fake's alive set

    real_records = h.store.records

    def records_then_finish(**kw):  # type: ignore[no-untyped-def]
        out = real_records(**kw)
        if kw:
            return out  # the per-chore schedule scan; only the full scan races
        done = running.with_usage(
            Usage(1, 1, 0.0, 1.0), backend="b", model="m", billing=Billing.NONE
        ).finish(RunStatus.SUCCEEDED, ended=T0, reason=None)
        h.store.write_record(done)  # the runner lands after the scan
        return out

    h.store.records = records_then_finish  # type: ignore[method-assign]
    report = tick(h.deps().as_tick_deps())
    assert report.interrupted == []
    final = h.store.read_record("brand-20260302T090000Z-aa")
    assert final is not None and final.status is RunStatus.SUCCEEDED
    assert not any(r["status"] == "INTERRUPTED" for r in h.store.ledger_rows())


def test_tick_files_an_invalid_definition_with_a_bad_stem_path_safely(
    tmp_path: Path,
) -> None:
    from chores.adapters.fs_store import FsRunStore

    h = FullHarness(tmp_path, chores={"tidy": COMMAND})
    (tmp_path / "home" / "chores" / "foo.bar.md").write_text(
        "---\nname: foo.bar\nkind: command\n---\n"
    )
    h.store = FsRunStore(tmp_path / "state")  # type: ignore[assignment]
    report = tick(h.deps().as_tick_deps())
    assert "INVALID-foo-bar" in report.invalid
    (rec,) = h.store.records(chore="INVALID-foo-bar")
    assert rec.status is RunStatus.INVALID and "'foo.bar'.md" in (rec.reason or "")
    assert rec.run_id.startswith("INVALID-foo-bar-")
    tick(h.deps().as_tick_deps())  # same error again: no second record
    assert len(h.store.records(chore="INVALID-foo-bar")) == 1


class DiesMidPass(FakeRunStore):
    """The pass blows up after the ledger check (an uncaught adapter error)."""

    def records(self, *, chore=None, since=None):  # type: ignore[no-untyped-def]
        raise RuntimeError("disk vanished")


def test_a_pass_that_dies_leaves_the_previous_tick_mark_in_place(
    tmp_path: Path,
) -> None:
    h = FullHarness(tmp_path, chores={"tidy": COMMAND})
    h.store = DiesMidPass()  # type: ignore[assignment]
    before = TickMark(at=h.clock.now_utc() - timedelta(minutes=5), ledger_rows=0)
    h.store.mark_tick(before)
    with pytest.raises(RuntimeError):
        tick(h.deps().as_tick_deps())
    assert h.store.last_tick() == before  # the next tick replays this window


def test_an_unparseable_config_admits_installs_and_runs_nothing(tmp_path: Path) -> None:
    from dataclasses import replace

    from click.testing import CliRunner

    from chores.cli.main import main

    h = FullHarness(tmp_path, chores={"tidy": COMMAND})
    (tmp_path / "home" / "config.yaml").write_text("ceiling: [not, a, map]\n")
    defs = h.definitions.load()
    assert defs.config_error is not None and "config.yaml" in defs.config_error
    report = tick(h.deps().as_tick_deps())
    assert any("nothing admitted" in w for w in report.warnings)
    assert h.launched == [] and h.store.records() == []
    outcome = run_chore("tidy", h.deps().as_run_deps())
    assert outcome.record is None and "refused: config.yaml" in outcome.message
    inst = LaunchdInstaller(home=tmp_path / "h", uid=7, run=lambda argv: 0)
    deps = replace(h.deps(), installer=inst, scheduler_installed=inst.installed)
    r = CliRunner().invoke(main, ["install"], obj=deps)
    assert r.exit_code == 1 and "install refused" in r.output and not inst.installed()


def test_an_invalid_record_missing_its_ledger_row_is_reconciled(
    tmp_path: Path,
) -> None:
    """The record and the ledger row are two writes. A record that lost its
    row (a crash between the two) is not honoured unpaid by the once-only
    INVALID dedup: the row is re-appended, and no second record is written."""
    from chores.application.context import ensure_ledgered

    h = FullHarness(tmp_path, chores={"bad": "---\nname: bad\nkind: prompt\n---\n"})
    tick(h.deps().as_tick_deps())
    (only,) = h.store.records(chore="bad")
    assert only.status is RunStatus.INVALID and h.store.ledger_count() == 1
    h.store._ledger.clear()  # the crash: record on disk, row never landed
    h.clock.advance(60)
    tick(h.deps().as_tick_deps())
    assert len(h.store.records(chore="bad")) == 1  # still deduplicated
    assert [r["run_id"] for r in h.store.ledger_rows()] == [only.run_id]
    assert ensure_ledgered(h.store, only) is False  # now accounted for


def test_a_mechanism_failing_in_the_tick_is_a_warning_not_invalid(
    tmp_path: Path,
) -> None:
    """A launcher or store failure while considering a chore leaves the
    definition valid: the tick warns and notifies, writes no INVALID record,
    and still marks liveness."""
    from dataclasses import replace

    from chores.adapters.fs_store import UnsafeStatePath

    h = FullHarness(tmp_path, chores={"tidy": COMMAND})
    h.store.mark_tick(
        TickMark(at=h.clock.now_utc() - timedelta(seconds=60), ledger_rows=0)
    )

    def boom(name: str) -> None:
        raise UnsafeStatePath("spawn.log is a symlink; refusing to log there")

    report = tick(replace(h.deps(), launch=boom).as_tick_deps())
    assert report.invalid == [] and h.store.records() == []
    assert any("tidy: tick could not act" in w for w in report.warnings)
    assert any("could not act" in n.text for n in h.store.notifications())
    assert h.store.last_tick() is not None


def test_tick_interruptions_trip_the_breaker_and_carry_artifacts(
    tmp_path: Path,
) -> None:
    """A runner that dies before finishing is a failure like any other: the
    tick's INTERRUPTED closes count toward the breaker, and the closed run
    dir carries the five artifacts with the reason in errors.log even when
    the runner never reached Artifacts.prepare()."""
    h = FullHarness(tmp_path, chores={"tidy": COMMAND}, config="failure_threshold: 2\n")
    for i in (1, 2):
        pending = RunRecord.pending(
            run_id=f"tidy-20260918T0{i}0000Z-dead",
            chore="tidy",
            kind=Kind.COMMAND,
            definition_rev="r",
            started=h.clock.now_utc() - timedelta(seconds=30),
        )
        h.store.write_record(
            pending.start(pid=4000 + i, pgid=4000 + i, process_start=1.0)
        )
    report = tick(h.deps().as_tick_deps())  # FakeProcess: no pid is alive
    assert len(report.interrupted) == 2
    for run_id in report.interrupted:
        assert set(h.store.artifacts(run_id)) == set(ARTIFACTS)
        assert "gone without a terminal status" in h.store.read_artifact(
            run_id, "errors.log"
        )
    assert h.store.chore_paused("tidy") is not None
    assert any(
        n.level == "alert" and "breaker" in n.text for n in h.store.notifications()
    )


def test_invalid_records_carry_the_declared_kind_or_unknown(tmp_path: Path) -> None:
    """An INVALID record says the kind the front matter declared when it
    parsed that far, else `unknown`; never a made-up `command`. And
    `unknown` is a record's word only: a definition cannot declare it."""
    from chores.domain.chore import InvalidChore

    h = FullHarness(
        tmp_path,
        chores={
            "badprompt": "---\nname: badprompt\nkind: prompt\n---\nno schedule\n",
            "broken": "---\nname: [\n---\n",
        },
    )
    defs = h.definitions.load()
    by_name = {i.name: i for i in defs.invalid}
    assert by_name["badprompt"].kind is Kind.PROMPT
    assert by_name["broken"].kind is Kind.UNKNOWN
    tick(h.deps().as_tick_deps())
    kinds = {r.chore: r.kind for r in h.store.records()}
    assert kinds == {"badprompt": Kind.PROMPT, "broken": Kind.UNKNOWN}
    r = run_chore("broken", h.deps().as_run_deps()).record
    assert r and r.status is RunStatus.INVALID and r.kind is Kind.UNKNOWN
    with pytest.raises(InvalidChore, match="kind must be one of"):
        Chore.from_mapping(
            {
                "name": "x",
                "schedule": "* * * * *",
                "kind": "unknown",
                "command": ["true"],
            },
            body="",
        )


def test_a_corrupt_ledger_stops_admission_and_is_reported(tmp_path: Path) -> None:
    """The ceilings are computed from the ledger, so an unreadable one admits
    nothing, alerts once and keeps liveness with the previous count; status
    still loads, with the problem listed."""
    from chores.adapters.fs_store import FsRunStore
    from chores.application.status import status

    store = FsRunStore(tmp_path / "state")
    (tmp_path / "state" / "ledger.ndjson").write_text(
        '{"run_id": "a"}\nnot json\n{"run_id": "b"}\n'
    )
    h = FullHarness(tmp_path, chores={"tidy": COMMAND})
    h.store = store  # type: ignore[assignment]
    store.mark_tick(
        TickMark(at=h.clock.now_utc() - timedelta(seconds=60), ledger_rows=2)
    )
    report = tick(h.deps().as_tick_deps())
    assert report.fired == [] and any("ledger unreadable" in w for w in report.warnings)
    assert any(
        n.level == "alert" and "unreadable" in n.text for n in store.notifications()
    )
    mark = store.last_tick()
    assert mark is not None and mark.ledger_rows == 2  # liveness kept, no shrink
    view = status(h.deps())
    assert any("ledger unreadable" in p for p in view.problems)
