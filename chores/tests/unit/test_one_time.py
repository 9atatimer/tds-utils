"""One-time chores and armed runs (CHORES-ONE-TIME.DESIGN.md, issue #399).

Each test is a row of that record's Behaviors and Interfaces table, driven
through the use cases with the shared fakes.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from chores.application.arm import arm_chore, cancel_armed
from chores.application.run import run_chore
from chores.application.status import status
from chores.application.tick import tick
from chores.domain.policies import held
from chores.domain.run import RunStatus

from ._harness import FullHarness

MANUAL = (
    "---\nname: smoke\nschedule: manual\nkind: command\ncommand: [echo, hi]\n"
    "timeout_sec: 5\n---\n"
)
MANUAL_CATCH_UP = (
    "---\nname: bad\nschedule: manual\ncatch_up: true\nkind: command\n"
    "command: [echo, hi]\n---\n"
)
MANUAL_PROMPT = (
    "---\nname: ask\nschedule: manual\nkind: prompt\nbackend: local\n"
    "budget: {tokens: 100}\n---\nHi.\n"
)
MANUAL_BATTERY = (
    "---\nname: smoke\nschedule: manual\nkind: command\ncommand: [echo, hi]\n"
    "defer_on_battery: true\ntimeout_sec: 5\n---\n"
)


def _harness(tmp_path: Path, **chores: str) -> FullHarness:
    return FullHarness(tmp_path, chores=chores, installed=True)


def _arm(h: FullHarness, name: str, minutes: float = 0) -> str:
    out = arm_chore(
        name,
        h.clock.now_utc() + timedelta(minutes=minutes),
        h.deps().as_run_deps(),
        armed_by="cli",
    )
    assert out.run_id is not None, out.message
    return out.run_id


def _status_of(h: FullHarness, run_id: str) -> RunStatus:
    record = h.store.read_record(run_id)
    assert record is not None
    return record.status


# --- definitions -------------------------------------------------------------


def test_a_manual_chore_is_valid_and_never_fires(tmp_path: Path) -> None:
    """Given schedule: manual, When ticks pass across two days, Then no run,
    MISSED or first-sight record is ever written for it."""
    h = _harness(tmp_path, smoke=MANUAL)
    for _ in range(3):
        report = tick(h.deps().as_tick_deps())
        assert report.fired == [] and "smoke" not in report.missed
        h.clock.advance(24 * 3600)
    assert h.store.records(chore="smoke") == []
    assert h.launched == []


def test_manual_with_catch_up_is_invalid(tmp_path: Path) -> None:
    """Given schedule: manual and catch_up: true, Then the chore is INVALID
    with a reason naming catch_up."""
    h = _harness(tmp_path, bad=MANUAL_CATCH_UP)
    tick(h.deps().as_tick_deps())
    records = h.store.records(chore="bad")
    assert records and records[0].status is RunStatus.INVALID
    assert "catch_up" in (records[0].reason or "")


# --- arming ------------------------------------------------------------------


def test_arming_writes_an_armed_record_and_starts_nothing(tmp_path: Path) -> None:
    h = _harness(tmp_path, smoke=MANUAL)
    run_id = _arm(h, "smoke", minutes=30)
    record = h.store.read_record(run_id)
    assert record is not None and record.status is RunStatus.ARMED
    assert record.start_at == h.clock.now_utc() + timedelta(minutes=30)
    assert record.armed_by == "cli"
    assert h.launched == [] and h.armed_launched == []
    assert not RunStatus.ARMED.is_terminal


def test_a_second_arming_is_refused_naming_the_first(tmp_path: Path) -> None:
    h = _harness(tmp_path, smoke=MANUAL)
    first = _arm(h, "smoke", minutes=30)
    out = arm_chore("smoke", h.clock.now_utc(), h.deps().as_run_deps(), armed_by="cli")
    assert out.run_id is None and first in out.message
    assert _status_of(h, first) is RunStatus.ARMED


def test_a_past_start_time_is_refused(tmp_path: Path) -> None:
    h = _harness(tmp_path, smoke=MANUAL)
    out = arm_chore(
        "smoke",
        h.clock.now_utc() - timedelta(minutes=30),
        h.deps().as_run_deps(),
        armed_by="cli",
    )
    assert out.run_id is None and "past" in out.message
    assert h.store.records(chore="smoke") == []


def test_arming_an_unknown_or_invalid_chore_is_refused(tmp_path: Path) -> None:
    h = _harness(tmp_path, bad=MANUAL_CATCH_UP)
    for name in ("nope", "bad"):
        out = arm_chore(name, h.clock.now_utc(), h.deps().as_run_deps(), armed_by="cli")
        assert out.run_id is None
    assert h.store.records(chore="nope") == []


# --- the tick ----------------------------------------------------------------


def test_an_armed_run_waits_for_its_time(tmp_path: Path) -> None:
    h = _harness(tmp_path, smoke=MANUAL)
    run_id = _arm(h, "smoke", minutes=30)
    tick(h.deps().as_tick_deps())
    assert h.armed_launched == [] and _status_of(h, run_id) is RunStatus.ARMED


def test_the_tick_fires_an_armed_run_at_its_time(tmp_path: Path) -> None:
    h = _harness(tmp_path, smoke=MANUAL)
    run_id = _arm(h, "smoke", minutes=30)
    h.clock.advance(30 * 60 + 20)
    report = tick(h.deps().as_tick_deps())
    assert h.armed_launched == [("smoke", run_id)]
    assert "smoke" in report.fired
    assert h.launched == []  # the plain launch is for cron slots


def test_admission_refusal_consumes_the_ask(tmp_path: Path) -> None:
    """Given PAUSED, When the armed time comes, Then SKIPPED_PAUSED, with the
    reason, and the ask is not retried."""
    h = _harness(tmp_path, smoke=MANUAL)
    run_id = _arm(h, "smoke")
    h.store.pause("maintenance")
    tick(h.deps().as_tick_deps())
    assert _status_of(h, run_id) is RunStatus.SKIPPED_PAUSED
    h.store.unpause()
    h.clock.advance(120)
    tick(h.deps().as_tick_deps())
    assert h.armed_launched == []
    rows = [r for r in h.store.ledger_rows() if r["run_id"] == run_id]
    assert [r["status"] for r in rows] == ["SKIPPED_PAUSED"]


def test_battery_keeps_the_arming_until_ac(tmp_path: Path) -> None:
    h = _harness(tmp_path, smoke=MANUAL_BATTERY)
    run_id = _arm(h, "smoke")
    h.power.battery = True
    tick(h.deps().as_tick_deps())
    assert _status_of(h, run_id) is RunStatus.ARMED and h.armed_launched == []
    h.power.battery = False
    h.clock.advance(60)
    tick(h.deps().as_tick_deps())
    assert h.armed_launched == [("smoke", run_id)]


def test_an_orphaned_arming_is_abandoned(tmp_path: Path) -> None:
    h = _harness(tmp_path, smoke=MANUAL)
    run_id = _arm(h, "smoke")
    (Path(h.paths.chores_home) / "chores" / "smoke.md").unlink()
    tick(h.deps().as_tick_deps())
    record = h.store.read_record(run_id)
    assert record is not None and record.status is RunStatus.ARM_ABANDONED
    assert "smoke" in (record.reason or "")
    assert h.armed_launched == []


# --- the runner --------------------------------------------------------------


def test_the_runner_adopts_the_armed_id(tmp_path: Path) -> None:
    """One run, one directory, one ledger row, under the armed id."""
    h = _harness(tmp_path, smoke=MANUAL)
    run_id = _arm(h, "smoke")
    out = run_chore("smoke", h.deps().as_run_deps(), armed_run_id=run_id)
    assert out.record is not None and out.record.run_id == run_id
    assert _status_of(h, run_id) is RunStatus.SUCCEEDED
    assert [r["run_id"] for r in h.store.ledger_rows()] == [run_id]
    assert len(h.store.records(chore="smoke")) == 1


def test_a_late_fire_is_recorded_not_missed(tmp_path: Path) -> None:
    h = _harness(tmp_path, smoke=MANUAL)
    run_id = _arm(h, "smoke", minutes=30)
    h.clock.advance(30 * 60 + 9000)
    run_chore("smoke", h.deps().as_run_deps(), armed_run_id=run_id)
    record = h.store.read_record(run_id)
    assert record is not None and record.status is RunStatus.SUCCEEDED
    assert record.late_sec == 9000


def test_a_cancelled_arming_cannot_be_run(tmp_path: Path) -> None:
    h = _harness(tmp_path, smoke=MANUAL)
    run_id = _arm(h, "smoke")
    assert cancel_armed(run_id, h.deps()) is True
    assert _status_of(h, run_id) is RunStatus.CANCELLED
    tick(h.deps().as_tick_deps())
    assert h.armed_launched == []
    out = run_chore("smoke", h.deps().as_run_deps(), armed_run_id=run_id)
    assert _status_of(h, run_id) is RunStatus.CANCELLED
    assert "armed" in out.message


def test_cancel_refuses_anything_not_armed(tmp_path: Path) -> None:
    h = _harness(tmp_path, smoke=MANUAL)
    out = run_chore("smoke", h.deps().as_run_deps())
    assert out.record is not None
    assert cancel_armed(out.record.run_id, h.deps()) is False
    assert cancel_armed("no-such-run", h.deps()) is False


# --- guarding and status -----------------------------------------------------


def test_an_armed_run_holds_no_budget(tmp_path: Path) -> None:
    h = _harness(tmp_path, ask=MANUAL_PROMPT)
    run_id = _arm(h, "ask", minutes=60)
    record = h.store.read_record(run_id)
    assert record is not None
    assert held(record, ledgered=False) is None


def test_status_shows_manual_and_the_arming(tmp_path: Path) -> None:
    h = _harness(tmp_path, smoke=MANUAL)
    view = status(h.deps())
    row = view.chores[0]
    assert row.schedule == "manual" and row.next_due is None and row.armed is None
    run_id = _arm(h, "smoke", minutes=30)
    row = status(h.deps()).chores[0]
    assert row.armed is not None and row.armed.run_id == run_id
    assert row.next_due == h.clock.now_local() + timedelta(minutes=30)


# --- the CLI -----------------------------------------------------------------


def _invoke(h: FullHarness, *args: str) -> tuple[int, str]:
    from click.testing import CliRunner

    from chores.cli.main import main

    result = CliRunner().invoke(main, list(args), obj=h.deps(), catch_exceptions=False)
    return result.exit_code, result.output


def test_cli_arms_now_and_by_local_clock_time(tmp_path: Path) -> None:
    """Given local 10:00 (UTC 17:00), When `run smoke --at 10:30`, Then the
    arming's start is 17:30 UTC; `--at now` arms for the current instant."""
    h = _harness(tmp_path, smoke=MANUAL)
    code, out = _invoke(h, "run", "smoke", "--at", "10:30")
    assert code == 0 and "armed as" in out, out
    armed = [r for r in h.store.records(chore="smoke") if r.status is RunStatus.ARMED]
    assert armed and armed[0].start_at == h.clock.now_utc().replace(minute=30, second=0)
    assert cancel_armed(armed[0].run_id, h.deps())
    code, out = _invoke(h, "run", "smoke", "--at", "now")
    assert code == 0 and "armed as" in out, out


def test_cli_refuses_at_with_force_or_dry_run(tmp_path: Path) -> None:
    h = _harness(tmp_path, smoke=MANUAL)
    for flag in ("--force", "--dry-run"):
        code, out = _invoke(h, "run", "smoke", "--at", "now", flag)
        assert code != 0 and "--at" in out, out
    assert h.store.records(chore="smoke") == []


def test_cli_cancel_and_armed_run(tmp_path: Path) -> None:
    h = _harness(tmp_path, smoke=MANUAL)
    first = _arm(h, "smoke", minutes=5)
    code, _ = _invoke(h, "cancel", first)
    assert code == 0 and _status_of(h, first) is RunStatus.CANCELLED
    code, _ = _invoke(h, "cancel", first)
    assert code != 0
    second = _arm(h, "smoke")
    code, out = _invoke(h, "run", "smoke", "--armed", second)
    assert code == 0 and _status_of(h, second) is RunStatus.SUCCEEDED, out


def test_cli_status_shows_manual_and_armed(tmp_path: Path) -> None:
    h = _harness(tmp_path, smoke=MANUAL)
    _arm(h, "smoke", minutes=30)
    code, out = _invoke(h, "status")
    assert code == 0 and "manual" in out and "armed" in out, out
