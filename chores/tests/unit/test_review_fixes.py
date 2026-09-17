"""Behaviors pinned by the adversarial self-review (session 2026-09-14):
secrets in reasons, escaping exceptions, the tick/run race, wall-clock spend,
ceilings on command chores, KILLED for agent runs, last_run semantics."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from chores.adapters.scheduler import LaunchdInstaller
from chores.application.run import run_chore
from chores.application.status import status
from chores.application.tick import tick
from chores.domain.budget import Ceiling
from chores.domain.chore import BackendSpec, Chore, check_bindings
from chores.domain.kinds import ExecutionPort, Kind
from chores.domain.run import RunRecord, RunStatus
from chores.domain.schedule import InvalidSchedule, Schedule
from chores.ports.errors import BackendError, ProcessError
from chores.ports.store import TickMark

from ._fakes import FakeAgent, FakeClock, FakeCompletion, FakeProcess
from ._harness import T0, FullHarness
from .test_runner import AGENT, COMMAND, PROMPT, SECRET


class FailingSpawn(FakeProcess):
    def spawn(self, request):  # type: ignore[no-untyped-def]
        raise ProcessError("could not start 'nope': No such file")


class TickingClock(FakeClock):
    """Every now_utc() call advances 30s: wall time passes during a run."""

    def now_utc(self) -> datetime:
        self.advance(30)
        return super().now_utc()


def test_reason_and_notification_are_redacted(tmp_path: Path) -> None:
    """Given a backend error that echoes the credential, Then reason, ledger and
    notification carry [REDACTED], not the value."""
    err = BackendError(f"HTTP 401 for token {SECRET}")
    h = FullHarness(
        tmp_path, chores={"brand": PROMPT}, completion=FakeCompletion(error=err)
    )
    r = run_chore("brand", h.deps().as_run_deps()).record
    assert r and r.status is RunStatus.FAILED and SECRET not in (r.reason or "")
    assert "[REDACTED]" in (r.reason or "")
    assert SECRET not in str(h.store.ledger_rows()[0]["reason"])
    assert all(SECRET not in n.text for n in h.store.notifications())


def test_process_error_is_failed_not_a_crash(tmp_path: Path) -> None:
    h = FullHarness(tmp_path, chores={"tidy": COMMAND}, process=FailingSpawn())
    r = run_chore("tidy", h.deps().as_run_deps()).record
    assert r and r.status is RunStatus.FAILED and "could not start" in (r.reason or "")


def test_never_matching_schedule_is_rejected_at_parse() -> None:
    with pytest.raises(InvalidSchedule):
        Schedule.parse("0 0 31 4 *")


def test_wall_clock_does_not_flip_a_success_to_budget_exceeded(tmp_path: Path) -> None:
    """Given a command with a 5s timeout whose wall time (secret resolution,
    snapshot) exceeds 5s, When it exits 0 in time, Then SUCCEEDED."""
    h = FullHarness(tmp_path, chores={"tidy": COMMAND})
    h.clock = TickingClock(T0, utc_offset=timedelta(hours=-7))
    r = run_chore("tidy", h.deps().as_run_deps()).record
    assert r and r.status is RunStatus.SUCCEEDED and r.usage and r.usage.seconds > 5


def test_command_chores_are_never_ceiling_refused(tmp_path: Path) -> None:
    h = FullHarness(tmp_path, chores={"tidy": COMMAND}, config="ceiling: {tokens: 1}\n")
    h.store.append_ledger(
        {
            "chore": "x",
            "backend": "gw",
            "billing": "metered",
            "tokens_in": 5,
            "tokens_out": 5,
            "usd": 0,
            "seconds": 1,
            "started": h.clock.now_utc().isoformat(),
        }
    )
    r = run_chore("tidy", h.deps().as_run_deps()).record
    assert r and r.status is RunStatus.SUCCEEDED


def test_agent_run_with_kill_marker_is_killed(tmp_path: Path) -> None:
    h = FullHarness(
        tmp_path, chores={"rev": AGENT}, agent=FakeAgent(error=BackendError("exit 143"))
    )
    h.store.request_kill("rev-20260302T170030Z-ab12")
    r = run_chore("rev", h.deps().as_run_deps()).record
    assert r and r.status is RunStatus.KILLED


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


def test_last_run_is_the_last_run_not_the_last_tick_outcome(tmp_path: Path) -> None:
    h = FullHarness(
        tmp_path, chores={"tidy": COMMAND}, process=FakeProcess(exit_code=1)
    )
    run_chore("tidy", h.deps().as_run_deps())
    h.clock.advance(60)
    h.store.pause("flight")
    run_chore("tidy", h.deps().as_run_deps())  # SKIPPED_PAUSED
    view = status(h.deps())
    assert (
        view.chores[0].last_run and view.chores[0].last_run.status is RunStatus.FAILED
    )
    assert view.needs_attention is True


def test_agent_needs_turns_and_a_model_must_exist() -> None:
    backend = BackendSpec(
        "claude", ExecutionPort.AGENT, None, True, True, Ceiling(), frozenset()
    )
    agent = Chore.from_mapping(
        {
            "name": "rev",
            "schedule": "0 9 * * *",
            "kind": "agent",
            "backend": "claude",
            "budget": {"tokens": 1},
        },
        body="x",
    )
    out = check_bindings(
        agent, backend=backend, global_ceiling=Ceiling(), forbidden_paths=()
    )
    assert any("turns" in v for v in out) and any("no model" in v for v in out)


def test_installer_reports_a_failed_bootstrap(tmp_path: Path) -> None:
    inst = LaunchdInstaller(
        home=tmp_path, uid=1, run=lambda argv: 1 if argv[1] == "bootstrap" else 0
    )
    assert any("failed" in a for a in inst.install(interval_sec=60))


# --- Copilot round 1 (PR #290) ---------------------------------------------


def test_run_ids_cannot_escape_the_runs_directory(tmp_path: Path) -> None:
    from chores.adapters.fs_store import FsRunStore, InvalidRunId

    store = FsRunStore(tmp_path / "s")
    assert store.read_record("../../etc/passwd") is None
    assert store.read_artifact("../x", "stdout.log") == ""
    with pytest.raises(InvalidRunId):
        store.request_kill("../../escape")
    assert not (tmp_path / "escape").exists()


def test_notification_ids_are_unique_across_writers(tmp_path: Path) -> None:
    from chores.adapters.fs_store import FsRunStore

    a, b = FsRunStore(tmp_path / "s"), FsRunStore(tmp_path / "s")
    ids = {
        a.notify(at=T0, level="info", text="x").id,
        b.notify(at=T0, level="info", text="y").id,
    }
    assert len(ids) == 2
    assert [n.text for n in a.notifications()] == ["x", "y"]


def test_systemd_service_names_the_runtime_path(tmp_path: Path) -> None:
    from chores.adapters.scheduler import SystemdInstaller

    inst = SystemdInstaller(home=tmp_path, run=lambda argv: 0)
    inst.install(interval_sec=60)
    service = (
        tmp_path / ".config" / "systemd" / "user" / "chores-tick.service"
    ).read_text()
    assert "Environment=PATH=%h/.tds/dist/current/bin" in service


def test_definition_snapshot_is_redacted(tmp_path: Path) -> None:
    """Given a definition body that pastes the credential literally, Then the
    snapshot carries [REDACTED]."""
    leaky = PROMPT.replace("Summarize.", f"Summarize. key={SECRET}")
    h = FullHarness(tmp_path, chores={"brand": leaky})
    r = run_chore("brand", h.deps().as_run_deps()).record
    assert r is not None
    snapshot = h.store.read_artifact(r.run_id, "definition.md")
    assert SECRET not in snapshot and "[REDACTED]" in snapshot


def test_malformed_prices_is_a_reported_error_not_a_crash(tmp_path: Path) -> None:
    from chores.adapters.definitions import DefinitionsLoader

    (tmp_path / "chores").mkdir()
    (tmp_path / "backends.yaml").write_text(
        "backends:\n  gw:\n    type: ollama\n    prices: []\n"
    )
    defs = DefinitionsLoader(tmp_path, revision_reader=lambda _: "r").load()
    assert any("prices" in e for e in defs.errors) and defs.backends == {}


def test_agent_spawn_failure_records_failed(tmp_path: Path) -> None:
    class SpawnFails(FakeAgent):
        def run(self, task, *, on_start):  # type: ignore[no-untyped-def]
            raise ProcessError("could not start 'claude'")

    h = FullHarness(tmp_path, chores={"rev": AGENT}, agent=SpawnFails())
    r = run_chore("rev", h.deps().as_run_deps()).record
    assert r and r.status is RunStatus.FAILED and "could not start" in (r.reason or "")


def test_status_warns_on_ledger_shrink_and_unpriced_usd_ceiling(tmp_path: Path) -> None:
    h = FullHarness(tmp_path, chores={"tidy": COMMAND})
    (tmp_path / "home" / "backends.yaml").write_text(
        "backends:\n  unused:\n    type: ollama\n    model: m\n"
        "    ceiling: {usd: 1.0}\n"
    )
    h.store.mark_tick(TickMark(at=h.clock.now_utc(), ledger_rows=5))
    view = status(h.deps())
    assert any("shrank" in w for w in view.warnings)
    assert any("'unused' has a usd ceiling" in w for w in view.warnings)


def test_refused_run_exits_3(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from chores.cli.main import main

    h = FullHarness(tmp_path, chores={"tidy": COMMAND})
    h.store.pause("flight")
    result = CliRunner().invoke(main, ["run", "tidy"], obj=h.deps())
    assert result.exit_code == 3 and "SKIPPED_PAUSED" in result.output
