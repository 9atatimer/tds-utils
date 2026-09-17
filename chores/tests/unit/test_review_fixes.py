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
from chores.ports.store import ARTIFACTS, TickMark

from ._fakes import FakeAgent, FakeClock, FakeCompletion, FakeProcess, FakeRunStore
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
    from chores.adapters.scheduler import SchedulerInstallFailed

    inst = LaunchdInstaller(
        home=tmp_path, uid=1, run=lambda argv: 1 if argv[1] == "bootstrap" else 0
    )
    with pytest.raises(SchedulerInstallFailed, match="bootstrap"):
        inst.install(interval_sec=60)
    assert inst.installed() is False


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
        "backends:\n  unused:\n    type: openai-compat\n    model: m\n"
        "    base_url: https://gw\n    ceiling: {usd: 1.0}\n"
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


# --- Copilot round 2 (PR #290) ---------------------------------------------


def test_generated_run_ids_are_accepted_by_the_filesystem_store(
    tmp_path: Path,
) -> None:
    """Given a real ``new_run_id`` (uppercase T and Z in the timestamp), Then the
    store writes it: the path-safety check must not reject the ids it stores."""
    from chores.adapters.fs_store import FsRunStore
    from chores.domain.run import new_run_id

    store = FsRunStore(tmp_path / "s")
    run_id = new_run_id("brand", at=T0, suffix="ab12")
    record = RunRecord.pending(
        run_id=run_id, chore="brand", kind=Kind.PROMPT, definition_rev="r", started=T0
    )
    store.write_record(record)
    assert store.read_record(run_id) == record
    assert (tmp_path / "s" / "runs" / "brand" / run_id / "run.json").exists()


def test_chore_names_cannot_escape_the_paused_directory(tmp_path: Path) -> None:
    from chores.adapters.fs_store import FsRunStore, InvalidChoreName

    store = FsRunStore(tmp_path / "s")
    for bad in ("../../outside", "..", "a/b", "UPPER"):
        with pytest.raises(InvalidChoreName):
            store.pause_chore(bad, "x")
        with pytest.raises(InvalidChoreName):
            store.resume_chore(bad)
        with pytest.raises(InvalidChoreName):
            store.chore_paused(bad)
    assert not (tmp_path / "outside").exists()
    store.pause_chore("log-brand", "why")
    assert store.chore_paused("log-brand") == "why"


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


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_budgets_and_ceilings_reject_non_finite_usd(value: float) -> None:
    from chores.domain.budget import Budget, InvalidBudget

    with pytest.raises(InvalidBudget):
        Budget(seconds=1, usd=value)
    with pytest.raises(InvalidBudget):
        Ceiling(usd=value)


def test_json_escaped_redaction_form_matches_the_json_encoder() -> None:
    """The escaped form must be exactly what ``json.dumps`` (ensure_ascii) emits,
    or a secret with a control, non-ASCII or astral character persists."""
    import json

    from hypothesis import given, settings
    from hypothesis import strategies as st

    from chores.domain.policies import redact, redaction_forms

    @settings(max_examples=200, deadline=None)
    @given(st.text(min_size=1))
    def check(secret: str) -> None:
        assert json.dumps(secret)[1:-1] in redaction_forms(secret)

    check()
    for secret in ("päss\bw\f", "\U0001f512key", 'a"b\\c/d'):
        encoded = json.dumps({"k": secret})
        assert secret not in redact(encoded, [secret])
        assert json.dumps(secret)[1:-1] not in redact(encoded, [secret])


def test_malformed_usage_counts_are_backend_errors() -> None:
    from chores.adapters.http import HttpResponse
    from chores.adapters.ollama import OllamaCompletion
    from chores.adapters.openai_compat import OpenAICompatCompletion
    from chores.ports.completion import CompletionRequest

    from .test_completion_adapters import FakeTransport

    req = CompletionRequest(
        prompt="p", model="m", timeout_sec=1.0, max_output_tokens=None
    )
    bad_openai = HttpResponse(
        200,
        {
            "choices": [{"message": {"content": "x"}}],
            "usage": {"prompt_tokens": "lots", "completion_tokens": 1},
        },
    )
    with pytest.raises(BackendError, match="prompt_tokens"):
        OpenAICompatCompletion(
            FakeTransport(bad_openai),
            base_url="u",
            auth_header="x-auth",
            credential="c",
            prices={},
            provider="p",
        ).complete(req)
    bad_ollama = HttpResponse(
        200, {"message": {"content": "x"}, "prompt_eval_count": "1", "eval_count": {}}
    )
    with pytest.raises(BackendError, match="eval_count"):
        OllamaCompletion(FakeTransport(bad_ollama), base_url="u").complete(req)


def test_network_probe_honours_the_requires_network_override() -> None:
    from chores.adapters.registry import BackendCatalog
    from chores.ports.backends import BackendConfig

    catalog = BackendCatalog(
        {
            "remote-ollama": BackendConfig(
                name="remote-ollama",
                type="ollama",
                model="m",
                base_url="http://box:11434",
                requires_network=True,
            )
        },
        process=FakeProcess(),
    )
    spec = catalog.spec("remote-ollama")
    assert spec is not None and spec.requires_network is True
    assert catalog.probe_url("remote-ollama") == "http://box:11434"


def test_probe_treats_a_malformed_url_as_unreachable() -> None:
    from chores.adapters.http import probe

    assert probe("https://host:bad-port", timeout_sec=0.01) is False
    assert probe("not a url", timeout_sec=0.01) is False


def test_failed_scheduler_enable_raises_and_leaves_nothing_behind(
    tmp_path: Path,
) -> None:
    from chores.adapters.scheduler import SchedulerInstallFailed, SystemdInstaller

    def enable_fails(argv: list[str]) -> int:
        return 1 if "enable" in argv or "bootstrap" in argv else 0

    launchd = LaunchdInstaller(home=tmp_path / "mac", uid=501, run=enable_fails)
    with pytest.raises(SchedulerInstallFailed):
        launchd.install(interval_sec=60)
    assert launchd.installed() is False
    systemd = SystemdInstaller(home=tmp_path / "linux", run=enable_fails)
    with pytest.raises(SchedulerInstallFailed):
        systemd.install(interval_sec=60)
    assert systemd.installed() is False


def test_cli_install_exits_1_when_the_scheduler_refuses(tmp_path: Path) -> None:
    from dataclasses import replace

    from click.testing import CliRunner

    from chores.cli.main import main

    inst = LaunchdInstaller(home=tmp_path / "h", uid=7, run=lambda argv: 1)
    h = FullHarness(tmp_path, chores={"tidy": COMMAND})
    deps = replace(h.deps(), installer=inst, scheduler_installed=inst.installed)
    r = CliRunner().invoke(main, ["install"], obj=deps)
    assert r.exit_code == 1 and "install failed" in r.output
    assert not inst.installed()


def test_systemd_path_includes_the_fresh_clone_tier(tmp_path: Path) -> None:
    from chores.adapters.scheduler import SystemdInstaller

    inst = SystemdInstaller(home=tmp_path, run=lambda argv: 0)
    inst.install(interval_sec=60)
    service = (
        tmp_path / ".config" / "systemd" / "user" / "chores-tick.service"
    ).read_text()
    assert "%h/workplace/tds-utils/bin" in service


# --- Copilot round 3 (PR #290) ---------------------------------------------


def test_prices_must_be_finite_and_non_negative(tmp_path: Path) -> None:
    from chores.ports.backends import Price

    for bad in (float("nan"), float("inf"), -0.01):
        with pytest.raises(ValueError):
            Price(in_per_1m=bad, out_per_1m=1.0)
    h = FullHarness(tmp_path, chores={"tidy": COMMAND})
    (tmp_path / "home" / "backends.yaml").write_text(
        "backends:\n  gw:\n    type: openai-compat\n    model: m\n"
        "    base_url: https://gw\n"
        "    prices: {m: {in_per_1m: .nan, out_per_1m: -1}}\n"
    )
    defs = h.definitions.load()
    assert any("price for m" in e for e in defs.errors)


def test_records_filter_cannot_escape_the_runs_directory(tmp_path: Path) -> None:
    from chores.adapters.fs_store import FsRunStore

    outside = tmp_path / "outside" / "x"
    outside.mkdir(parents=True)
    (outside / "run.json").write_text("{}")
    store = FsRunStore(tmp_path / "s")
    assert store.records(chore="../../outside") == []
    assert store.records(chore="../outside") == []


def test_a_young_pending_record_counts_as_live_for_overlap(tmp_path: Path) -> None:
    """Given a PENDING record seconds old (the runner has not spawned yet),
    Then a concurrent manual run is SKIPPED_OVERLAP; a PENDING older than one
    tick interval is not live (it is the tick's to interrupt)."""
    from chores.application.context import live_running

    h = FullHarness(tmp_path, chores={"brand": PROMPT})
    young = RunRecord.pending(
        run_id="brand-a",
        chore="brand",
        kind=Kind.PROMPT,
        definition_rev="r",
        started=h.clock.now_utc() - timedelta(seconds=5),
    )
    h.store.write_record(young)
    grace = timedelta(seconds=60)
    now = h.clock.now_utc()
    live = live_running(h.store, h.process, "brand", now_utc=now, pending_grace=grace)
    assert live is not None and live.run_id == "brand-a"
    r = run_chore("brand", h.deps().as_run_deps()).record
    assert r and r.status is RunStatus.SKIPPED_OVERLAP and "brand-a" in (r.reason or "")
    stale = RunRecord.pending(
        run_id="brand-b",
        chore="brand",
        kind=Kind.PROMPT,
        definition_rev="r",
        started=h.clock.now_utc() - timedelta(minutes=10),
    )
    h.store.write_record(stale)
    h.store.delete_run("brand-a")
    assert (
        live_running(h.store, h.process, "brand", now_utc=now, pending_grace=grace)
        is None
    )


@pytest.mark.parametrize("cost", ["nan", "inf", "-0.5"])
def test_provider_costs_must_be_finite_and_non_negative(cost: str) -> None:
    from chores.adapters._fields import float_field, int_field

    with pytest.raises(BackendError, match="total_cost_usd"):
        float_field(cost, provider="p", field="total_cost_usd")
    with pytest.raises(BackendError, match="negative"):
        int_field(-1, provider="p", field="output_tokens")


def test_overlapping_data_and_state_roots_are_refused(tmp_path: Path) -> None:
    from chores.application.paths import OverlappingRoots, Paths
    from chores.cli.wiring import resolve_paths

    with pytest.raises(OverlappingRoots):
        Paths(
            str(tmp_path / "home"),
            str(tmp_path / "state"),
            str(tmp_path / "state" / "d"),
        )
    with pytest.raises(OverlappingRoots):
        Paths(
            str(tmp_path / "home"), str(tmp_path / "d" / "state"), str(tmp_path / "d")
        )
    with pytest.raises(OverlappingRoots):
        resolve_paths(
            {
                "HOME": str(tmp_path),
                "XDG_STATE_HOME": str(tmp_path / "st"),
                "XDG_DATA_HOME": str(tmp_path / "st" / "chores" / "data"),
            }
        )


def test_roots_are_resolved_so_a_symlinked_state_dir_cannot_be_reached(
    tmp_path: Path,
) -> None:
    from chores.cli.wiring import resolve_paths

    real = tmp_path / "real-state"
    real.mkdir()
    link = tmp_path / "link-state"
    link.symlink_to(real)
    paths = resolve_paths({"HOME": str(tmp_path), "XDG_STATE_HOME": str(link)})
    assert paths.state_dir == str(real / "chores")
    assert str(real / "chores") in paths.forbidden_for_cwd()


def test_cli_refuses_to_start_on_overlapping_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from click.testing import CliRunner

    import chores.cli.wiring as wiring
    from chores.cli.main import main

    def boom() -> None:
        raise ValueError("data dir overlaps the state dir")

    monkeypatch.setattr(wiring, "build_deps", boom)
    r = CliRunner().invoke(main, ["status"])
    assert r.exit_code == 1 and "overlaps" in r.output


def _write_bad_stem(tmp_path: Path) -> None:
    (tmp_path / "home" / "chores" / "foo.bar.md").write_text(
        "---\nname: foo.bar\nkind: command\n---\n"
    )


def test_tick_files_an_invalid_definition_with_a_bad_stem_path_safely(
    tmp_path: Path,
) -> None:
    from chores.adapters.fs_store import FsRunStore

    h = FullHarness(tmp_path, chores={"tidy": COMMAND})
    _write_bad_stem(tmp_path)
    h.store = FsRunStore(tmp_path / "state")  # type: ignore[assignment]
    report = tick(h.deps().as_tick_deps())
    assert "INVALID-foo-bar" in report.invalid
    (rec,) = h.store.records(chore="INVALID-foo-bar")
    assert rec.status is RunStatus.INVALID and "'foo.bar'.md" in (rec.reason or "")
    assert rec.run_id.startswith("INVALID-foo-bar-")
    tick(h.deps().as_tick_deps())  # same error again: no second record
    assert len(h.store.records(chore="INVALID-foo-bar")) == 1


def test_manual_run_of_a_bad_stem_definition_records_invalid(tmp_path: Path) -> None:
    from chores.adapters.fs_store import FsRunStore

    h = FullHarness(tmp_path, chores={"tidy": COMMAND})
    _write_bad_stem(tmp_path)
    h.store = FsRunStore(tmp_path / "state")  # type: ignore[assignment]
    r = run_chore("foo.bar", h.deps().as_run_deps()).record
    assert r is not None and r.status is RunStatus.INVALID
    assert r.chore == "INVALID-foo-bar" and h.store.read_record(r.run_id) == r


# --- Copilot round 4 (PR #290) ---------------------------------------------


class TickWinsTheStart(FakeRunStore):
    """The tick closes the stale PENDING record before the runner starts."""

    def write_record(self, record: RunRecord) -> None:
        super().write_record(record)
        if record.status is RunStatus.PENDING:
            super().write_record(
                record.finish(
                    RunStatus.INTERRUPTED, ended=record.started, reason="tick"
                )
            )


class TickWinsTheFinish(FakeRunStore):
    """The tick closes the RUNNING record before the runner's own finish."""

    def transition(self, run_id, *, expected, then):  # type: ignore[no-untyped-def]
        if expected is RunStatus.RUNNING:
            current = self.read_record(run_id)
            assert current is not None
            super().write_record(
                current.finish(RunStatus.INTERRUPTED, ended=current.started, reason="t")
            )
            return None
        return super().transition(run_id, expected=expected, then=then)


def test_runner_that_loses_the_start_race_stops_and_writes_nothing(
    tmp_path: Path,
) -> None:
    h = FullHarness(tmp_path, chores={"tidy": COMMAND})
    h.store = TickWinsTheStart()  # type: ignore[assignment]
    outcome = run_chore("tidy", h.deps().as_run_deps())
    assert outcome.record is not None
    assert outcome.record.status is RunStatus.INTERRUPTED
    assert "lost the start race" in outcome.message
    assert h.store.ledger_rows() == []  # the runner appended no row of its own
    assert len(h.process.signalled) == 1  # the already-spawned child was stopped
    assert "lost the start race" in h.store.read_artifact(
        outcome.record.run_id, "errors.log"
    )


def test_runner_that_loses_the_finish_race_keeps_the_ticks_record(
    tmp_path: Path,
) -> None:
    h = FullHarness(tmp_path, chores={"tidy": COMMAND})
    h.store = TickWinsTheFinish()  # type: ignore[assignment]
    outcome = run_chore("tidy", h.deps().as_run_deps())
    assert outcome.record is not None
    assert outcome.record.status is RunStatus.INTERRUPTED
    assert h.store.ledger_rows() == []
    assert "not recorded" in h.store.read_artifact(outcome.record.run_id, "errors.log")
    assert h.notifier.alerts == []


def test_agent_killed_child_with_nonzero_exit_records_killed(tmp_path: Path) -> None:
    """A killed claude child exits nonzero and returns a normal AgentResult;
    the kill marker, not the exit code, decides the status."""
    h = FullHarness(tmp_path, chores={"rev": AGENT}, agent=FakeAgent(exit_code=143))
    h.store.request_kill("rev-20260302T170030Z-ab12")
    r = run_chore("rev", h.deps().as_run_deps()).record
    assert r and r.status is RunStatus.KILLED and r.exit_code == 143


def test_scheduler_units_persist_the_roots_chosen_at_install(tmp_path: Path) -> None:
    from chores.adapters.scheduler import SystemdInstaller

    env = {"CHORES_HOME": "/Users/t/workplace/tds-internal/ops/chores"}
    launchd = LaunchdInstaller(home=tmp_path / "mac", uid=501, run=lambda a: 0)
    launchd.install(interval_sec=60, env={**env, "XDG_STATE_HOME": "/a b/c"})
    plist = launchd.plist.read_text()
    assert "<key>CHORES_HOME</key>" in plist and env["CHORES_HOME"] in plist
    assert "<key>XDG_STATE_HOME</key>\n    <string>/a b/c</string>" in plist
    systemd = SystemdInstaller(home=tmp_path / "linux", run=lambda a: 0)
    systemd.install(interval_sec=60, env={**env, "XDG_STATE_HOME": "/a b/c"})
    service = (systemd.unit_dir / "chores-tick.service").read_text()
    assert f'Environment="CHORES_HOME={env["CHORES_HOME"]}"' in service
    assert 'Environment="XDG_STATE_HOME=/a b/c"' in service
    assert "Environment=PATH=" in service


def test_cli_install_passes_the_definitions_root_to_the_unit(tmp_path: Path) -> None:
    from dataclasses import replace

    from click.testing import CliRunner

    from chores.cli.main import main

    inst = LaunchdInstaller(home=tmp_path / "h", uid=7, run=lambda argv: 0)
    h = FullHarness(
        tmp_path, chores={"tidy": COMMAND}, env={"XDG_STATE_HOME": str(tmp_path)}
    )
    deps = replace(h.deps(), installer=inst, scheduler_installed=inst.installed)
    r = CliRunner().invoke(main, ["install"], obj=deps, catch_exceptions=False)
    assert r.exit_code == 0
    plist = inst.plist.read_text()
    assert f"<string>{h.paths.chores_home}</string>" in plist
    assert f"<string>{tmp_path}</string>" in plist


# --- Copilot round 5 (PR #290) ---------------------------------------------


def test_kill_never_signals_a_group_whose_process_is_gone(tmp_path: Path) -> None:
    from chores.application.status import kill

    h = FullHarness(tmp_path, chores={"tidy": COMMAND})
    gone = RunRecord.pending(
        run_id="tidy-a", chore="tidy", kind=Kind.COMMAND, definition_rev="r", started=T0
    ).start(pid=9, pgid=9, process_start=1.0)
    h.store.write_record(gone)  # pid 9 is not alive in the fake
    assert "already gone" in kill(h.deps(), "tidy-a")
    assert h.process.signalled == [] and not h.store.kill_requested("tidy-a")
    h.process.alive_pids.add(9)
    assert "signalled group 9" in kill(h.deps(), "tidy-a")
    assert h.process.signalled == [9] and h.store.kill_requested("tidy-a")


def test_usd_limits_need_the_resolved_model_to_be_priced() -> None:
    from chores.domain.budget import Budget

    gw = BackendSpec(
        name="gw",
        port=ExecutionPort.COMPLETION,
        default_model="m",
        requires_network=True,
        priced=True,
        ceiling=Ceiling(),
        read_only_tools=frozenset(),
        priced_models=frozenset({"m"}),
    )
    base = Chore.from_mapping(
        {
            "name": "p",
            "kind": "prompt",
            "schedule": "* * * * *",
            "backend": "gw",
            "timeout_sec": 5,
            "model": "other",
        },
        body="x",
    )
    assert not check_bindings(
        base, backend=gw, global_ceiling=Ceiling(), forbidden_paths=()
    )
    errors = check_bindings(
        base, backend=gw, global_ceiling=Ceiling(usd=1.0), forbidden_paths=()
    )
    assert any("'other' has no price" in e for e in errors)
    with_budget = Chore.from_mapping(
        {
            "name": "p",
            "kind": "prompt",
            "schedule": "* * * * *",
            "backend": "gw",
            "timeout_sec": 5,
            "model": "other",
            "budget": {"usd": 0.5},
        },
        body="x",
    )
    assert isinstance(with_budget.budget, Budget)
    errors = check_bindings(
        with_budget, backend=gw, global_ceiling=Ceiling(), forbidden_paths=()
    )
    assert any("'other' has no price" in e for e in errors)
    priced = Chore.from_mapping(
        {
            "name": "p",
            "kind": "prompt",
            "schedule": "* * * * *",
            "backend": "gw",
            "timeout_sec": 5,
            "budget": {"usd": 0.5},
        },
        body="x",
    )
    assert not check_bindings(
        priced, backend=gw, global_ceiling=Ceiling(), forbidden_paths=()
    )


def test_catalog_refuses_an_openai_compat_backend_without_base_url() -> None:
    from chores.adapters.registry import BackendCatalog
    from chores.ports.backends import BackendConfig

    catalog = BackendCatalog(
        {"gw": BackendConfig(name="gw", type="openai-compat", model="m")},
        process=FakeProcess(),
    )
    assert catalog.spec("gw") is None
    assert any("needs base_url" in e for e in catalog.errors)


def test_loader_rejects_unknown_ceiling_keys_and_non_bool_requires_network(
    tmp_path: Path,
) -> None:
    h = FullHarness(tmp_path, chores={"tidy": COMMAND})
    (tmp_path / "home" / "backends.yaml").write_text(
        "backends:\n  a:\n    type: ollama\n    model: m\n"
        "    ceiling: {usd: 1, usdd: 2}\n"
        "  b:\n    type: ollama\n    model: m\n    requires_network: 'false'\n"
    )
    errors = h.definitions.load().errors
    assert any("unknown dimensions ['usdd']" in e for e in errors)
    assert any("requires_network must be true or false" in e for e in errors)


def test_linux_battery_detection_covers_named_mains_and_battery_status(
    tmp_path: Path,
) -> None:
    from chores.adapters.host import linux_on_battery

    def supply(name: str, **files: str) -> None:
        d = tmp_path / name
        d.mkdir(parents=True, exist_ok=True)
        for k, v in files.items():
            (d / k).write_text(v + "\n")

    assert linux_on_battery(tmp_path / "missing") is False
    supply("ADP1", type="Mains", online="0")
    supply("BAT0", type="Battery", status="Discharging")
    assert linux_on_battery(tmp_path) is True
    supply("ADP1", type="Mains", online="1")
    assert linux_on_battery(tmp_path) is False  # mains decides over the battery
    import shutil

    shutil.rmtree(tmp_path / "ADP1")
    assert linux_on_battery(tmp_path) is True  # no mains: battery status decides
    supply("BAT0", type="Battery", status="Charging")
    assert linux_on_battery(tmp_path) is False


def test_systemd_environment_values_are_escaped(tmp_path: Path) -> None:
    from chores.adapters.scheduler import SchedulerInstallFailed, SystemdInstaller

    inst = SystemdInstaller(home=tmp_path, run=lambda a: 0)
    inst.install(interval_sec=60, env={"CHORES_HOME": '/h/"odd"\\100%'})
    service = (inst.unit_dir / "chores-tick.service").read_text()
    assert 'Environment="CHORES_HOME=/h/\\"odd\\"\\\\100%%"' in service
    with pytest.raises(SchedulerInstallFailed):
        inst.install(interval_sec=60, env={"CHORES_HOME": "/a\nb"})


def test_install_remembers_chores_home_for_shell_less_entry_points(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    from click.testing import CliRunner

    from chores.cli.main import main
    from chores.cli.wiring import resolve_paths

    inst = LaunchdInstaller(home=tmp_path / "h", uid=7, run=lambda argv: 0)
    h = FullHarness(tmp_path, chores={"tidy": COMMAND})
    deps = replace(h.deps(), installer=inst, scheduler_installed=inst.installed)
    r = CliRunner().invoke(main, ["install"], obj=deps, catch_exceptions=False)
    assert r.exit_code == 0 and "remembered CHORES_HOME" in r.output
    state_home = tmp_path  # h.paths.state_dir is <tmp_path>/state, not XDG-shaped
    env = {"HOME": str(tmp_path / "nohome")}
    (tmp_path / "xdg" / "chores").mkdir(parents=True)
    (tmp_path / "xdg" / "chores" / "home").write_text(h.paths.chores_home + "\n")
    env["XDG_STATE_HOME"] = str(tmp_path / "xdg")
    assert resolve_paths(env).chores_home == h.paths.chores_home
    assert resolve_paths(
        {**env, "CHORES_HOME": str(tmp_path / "x")}
    ).chores_home == str(tmp_path / "x")
    assert (Path(h.paths.state_dir) / "home").read_text().strip() == h.paths.chores_home
    r = CliRunner().invoke(main, ["uninstall"], obj=deps, catch_exceptions=False)
    assert r.exit_code == 0 and not (Path(h.paths.state_dir) / "home").exists()
    del state_home


# --- Copilot round 6 (PR #290) ---------------------------------------------


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


def test_a_metered_backend_without_prices_cannot_carry_any_usd_limit() -> None:
    from chores.domain.run import Billing

    def spec(billing: Billing) -> BackendSpec:
        return BackendSpec(
            name="b",
            port=ExecutionPort.COMPLETION,
            default_model="m",
            requires_network=True,
            priced=False,
            ceiling=Ceiling(),
            read_only_tools=frozenset(),
            billing=billing,
        )

    chore = Chore.from_mapping(
        {
            "name": "p",
            "kind": "prompt",
            "schedule": "* * * * *",
            "backend": "b",
            "timeout_sec": 5,
            "budget": {"usd": 0.5},
        },
        body="x",
    )
    metered = check_bindings(
        chore,
        backend=spec(Billing.METERED),
        global_ceiling=Ceiling(),
        forbidden_paths=(),
    )
    assert any("metered but has no price table" in e for e in metered)
    free = check_bindings(
        chore, backend=spec(Billing.NONE), global_ceiling=Ceiling(), forbidden_paths=()
    )
    assert free == []
    plain = Chore.from_mapping(
        {
            "name": "p",
            "kind": "prompt",
            "schedule": "* * * * *",
            "backend": "b",
            "timeout_sec": 5,
        },
        body="x",
    )
    global_cap = check_bindings(
        plain,
        backend=spec(Billing.METERED),
        global_ceiling=Ceiling(usd=2.0),
        forbidden_paths=(),
    )
    assert any("metered but has no price table" in e for e in global_cap)


def test_registry_types_declare_their_billing() -> None:
    from chores.adapters.registry import BackendCatalog
    from chores.domain.run import Billing
    from chores.ports.backends import BackendConfig

    catalog = BackendCatalog(
        {
            "local": BackendConfig(name="local", type="ollama", model="m"),
            "gw": BackendConfig(
                name="gw", type="openai-compat", model="m", base_url="https://gw"
            ),
            "claude": BackendConfig(name="claude", type="claude-cli", model="s"),
        },
        process=FakeProcess(),
    )
    billing = {n: catalog.spec(n).billing for n in ("local", "gw", "claude")}  # type: ignore[union-attr]
    assert billing == {
        "local": Billing.NONE,
        "gw": Billing.METERED,
        "claude": Billing.SUBSCRIPTION,
    }


def test_delete_run_reports_what_is_left_on_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    from chores.adapters.fs_store import FsRunStore

    store = FsRunStore(tmp_path / "s")
    store.write_record(
        RunRecord.pending(
            run_id="c-1", chore="c", kind=Kind.COMMAND, definition_rev="r", started=T0
        )
    )

    def refuse(path, *a, **kw):  # type: ignore[no-untyped-def]
        raise OSError("busy")

    monkeypatch.setattr(shutil, "rmtree", refuse)
    assert store.delete_run("c-1") is False  # the directory is still there
    assert store.read_record("c-1") is not None
    monkeypatch.undo()
    assert store.delete_run("c-1") is True and store.read_record("c-1") is None


# --- Copilot round 7 (PR #290) ---------------------------------------------


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


def test_definition_snapshot_is_the_source_that_was_parsed(tmp_path: Path) -> None:
    """A re-read after secret resolution could see a newer file; the snapshot
    must be the text the executed Chore came from."""
    from chores.adapters.definitions import DefinitionsLoader

    class ReReadsDifferently(DefinitionsLoader):
        def source(self, name: str) -> str | None:
            return "TAMPERED\n"

    h = FullHarness(tmp_path, chores={"tidy": COMMAND})
    h.definitions = ReReadsDifferently(tmp_path / "home", revision_reader=lambda _: "r")
    r = run_chore("tidy", h.deps().as_run_deps()).record
    assert r is not None and r.status is RunStatus.SUCCEEDED
    snapshot = h.store.read_artifact(r.run_id, "definition.md")
    assert "TAMPERED" not in snapshot and snapshot == COMMAND


def test_free_and_subscription_backends_may_carry_a_usd_ceiling_unpriced(
    tmp_path: Path,
) -> None:
    from chores.domain.run import Billing

    h = FullHarness(tmp_path, chores={"tidy": COMMAND})
    (tmp_path / "home" / "backends.yaml").write_text(
        "backends:\n"
        "  local: {type: ollama, model: m, ceiling: {usd: 1.0}}\n"
        "  claude: {type: claude-cli, model: s, ceiling: {usd: 1.0}}\n"
        "  metered: {type: openai-compat, model: m, base_url: 'https://gw',"
        " ceiling: {usd: 1.0}}\n"
    )
    view = status(h.deps())
    assert [w for w in view.warnings if "'metered' has a usd ceiling" in w]
    assert not [w for w in view.warnings if "'local'" in w or "'claude'" in w]

    def spec(billing: Billing) -> BackendSpec:
        return BackendSpec(
            name="b",
            port=ExecutionPort.COMPLETION,
            default_model="m",
            requires_network=False,
            priced=False,
            ceiling=Ceiling(usd=1.0),
            read_only_tools=frozenset(),
            billing=billing,
        )

    chore = Chore.from_mapping(
        {
            "name": "p",
            "kind": "prompt",
            "schedule": "* * * * *",
            "backend": "b",
            "timeout_sec": 5,
            "budget": {"usd": 0.5},
        },
        body="x",
    )
    for free in (Billing.NONE, Billing.SUBSCRIPTION):
        assert not check_bindings(
            chore, backend=spec(free), global_ceiling=Ceiling(), forbidden_paths=()
        )
    assert check_bindings(
        chore,
        backend=spec(Billing.METERED),
        global_ceiling=Ceiling(),
        forbidden_paths=(),
    )


def test_uninstall_fails_loudly_when_the_os_keeps_the_unit_loaded(
    tmp_path: Path,
) -> None:
    from chores.adapters.scheduler import SchedulerInstallFailed, SystemdInstaller

    def stuck(argv: list[str]) -> int:
        if argv[:2] == ["launchctl", "bootout"] or "disable" in argv:
            return 1  # could not unload / stop
        return 0  # `launchctl print` / `is-active`: still loaded

    def not_loaded(argv: list[str]) -> int:
        ok = ("bootstrap", "enable", "daemon-reload")
        return 0 if any(word in argv for word in ok) else 1

    launchd = LaunchdInstaller(home=tmp_path / "mac", uid=1, run=stuck)
    launchd.install(interval_sec=60)
    with pytest.raises(SchedulerInstallFailed, match="still loaded"):
        launchd.uninstall()
    assert launchd.installed() is True  # the plist is left in place
    launchd = LaunchdInstaller(home=tmp_path / "mac2", uid=1, run=not_loaded)
    launchd.install(interval_sec=60)
    launchd.uninstall()  # bootout nonzero but not loaded: idempotent
    assert launchd.installed() is False
    systemd = SystemdInstaller(home=tmp_path / "linux", run=stuck)
    systemd.install(interval_sec=60)
    with pytest.raises(SchedulerInstallFailed, match="still active"):
        systemd.uninstall()
    assert systemd.installed() is True
    systemd = SystemdInstaller(home=tmp_path / "linux2", run=not_loaded)
    systemd.install(interval_sec=60)
    systemd.uninstall()
    assert systemd.installed() is False


# --- Copilot round 8 (PR #290) ---------------------------------------------


def test_default_workspace_never_follows_a_symlink(tmp_path: Path) -> None:
    from chores.adapters.fs_store import FsWorkspaces, UnsafeWorkspace

    root = tmp_path / "data" / "workspaces"
    state = tmp_path / "state"
    state.mkdir()
    ws = FsWorkspaces(root)
    assert ws.ensure("tidy") == str(root / "tidy")
    (root / "evil").symlink_to(state)
    with pytest.raises(UnsafeWorkspace, match="symlink"):
        ws.ensure("evil")
    linked_root = tmp_path / "linked"
    linked_root.symlink_to(state)
    with pytest.raises(UnsafeWorkspace, match="symlink"):
        FsWorkspaces(linked_root).ensure("tidy")
    with pytest.raises(Exception, match="not a chore name"):
        ws.ensure("../escape")


@pytest.mark.parametrize("url", ["https://host:bad-port/v1", "not a url"])
def test_a_malformed_url_is_a_transport_error_not_a_crash(url: str) -> None:
    from chores.adapters.http import TransportError, UrllibTransport

    with pytest.raises(TransportError, match="malformed url"):
        UrllibTransport().post_json(url, headers={}, body={}, timeout_sec=0.01)


@pytest.mark.parametrize("url", ["ftp://gw/v1", "https://host:bad-port", "gw.example"])
def test_catalog_refuses_a_malformed_base_url(url: str) -> None:
    from chores.adapters.registry import BackendCatalog
    from chores.ports.backends import BackendConfig

    catalog = BackendCatalog(
        {"gw": BackendConfig(name="gw", type="openai-compat", model="m", base_url=url)},
        process=FakeProcess(),
    )
    assert catalog.spec("gw") is None and any("base_url" in e for e in catalog.errors)


def test_empty_xdg_values_are_unset_not_the_working_directory(tmp_path: Path) -> None:
    from chores.cli.wiring import resolve_paths

    paths = resolve_paths(
        {"HOME": str(tmp_path), "XDG_STATE_HOME": "", "XDG_DATA_HOME": ""}
    )
    assert paths.state_dir == str(tmp_path / ".local" / "state" / "chores")
    assert paths.data_dir == str(tmp_path / ".local" / "share" / "chores")


# --- Copilot round 9 (PR #290) ---------------------------------------------


def test_process_identity_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unknown recorded start, or a start ps cannot give now, never vouches
    for a pid: alive() is False, so the tick closes the run and kill never
    signals a possibly recycled group."""
    import os

    import chores.adapters.process as process
    from chores.adapters.process import UNKNOWN_START, SubprocessRunner

    runner = SubprocessRunner()
    me = os.getpid()
    assert runner.alive(me, process_start=UNKNOWN_START) is False
    monkeypatch.setattr(process, "process_start_time", lambda pid: None)
    assert runner.alive(me, process_start=12345.0) is False
    assert runner.own_identity().process_start == UNKNOWN_START  # not a guess
    monkeypatch.setattr(process, "process_start_time", lambda pid: 500.0)
    assert runner.alive(me, process_start=501.0) is True
    assert runner.alive(me, process_start=900.0) is False


def test_ps_is_read_in_the_c_locale(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    from chores.adapters.process import process_start_time

    seen: dict[str, str] = {}

    def fake_run(argv, **kw):  # type: ignore[no-untyped-def]
        seen.update(kw["env"])
        return subprocess.CompletedProcess(argv, 0, "Wed Sep 17 12:00:00 2026\n", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert process_start_time(1) is not None
    assert seen["LC_ALL"] == "C" and seen["LC_TIME"] == "C"


def test_a_kill_request_outranks_the_timeout(tmp_path: Path) -> None:
    h = FullHarness(
        tmp_path, chores={"tidy": COMMAND}, process=FakeProcess(timed_out=True)
    )
    h.store.request_kill("tidy-20260302T170030Z-ab12")
    r = run_chore("tidy", h.deps().as_run_deps()).record
    assert r and r.status is RunStatus.KILLED
    h = FullHarness(
        tmp_path / "a", chores={"rev": AGENT}, agent=FakeAgent(timed_out=True)
    )
    h.store.request_kill("rev-20260302T170030Z-ab12")
    r = run_chore("rev", h.deps().as_run_deps()).record
    assert r and r.status is RunStatus.KILLED


def test_dry_run_plan_shows_the_port_and_applicable_ceilings(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from chores.cli.main import main

    h = FullHarness(
        tmp_path, chores={"brand": PROMPT}, config="ceiling: {tokens: 5000}\n"
    )
    out = run_chore("brand", h.deps().as_run_deps(), dry_run=True)
    assert out.plan is not None and out.plan.port == "completion"
    assert set(out.plan.ceilings) == {"backend", "global"}  # gw caps usd; global tokens
    assert out.plan.ceilings["global"].tokens == 5000
    r = CliRunner().invoke(main, ["run", "brand", "--dry-run"], obj=h.deps())
    assert "port completion" in r.output
    assert "ceiling:   global:" in r.output and "ceiling:   backend:" in r.output


# --- Copilot round 10 (PR #290) --------------------------------------------


def test_state_tree_never_follows_a_symlinked_component(tmp_path: Path) -> None:
    from chores.adapters.fs_store import FsRunStore, UnsafeStatePath

    outside = tmp_path / "outside"
    outside.mkdir()
    store = FsRunStore(tmp_path / "s")
    (store.runs / "evil").symlink_to(outside)
    record = RunRecord.pending(
        run_id="evil-20260302T100000Z-ab12",
        chore="evil",
        kind=Kind.COMMAND,
        definition_rev="r",
        started=T0,
    )
    with pytest.raises(UnsafeStatePath, match="symlink"):
        store.write_record(record)
    assert list(outside.iterdir()) == []  # nothing was written through the link
    with pytest.raises(UnsafeStatePath):
        store.read_record(record.run_id)
    (store.runs / "good").mkdir()
    (store.runs / "good" / "good-20260302T100000Z-ab12").symlink_to(outside)
    with pytest.raises(UnsafeStatePath):
        store.append_artifact("good-20260302T100000Z-ab12", "stdout.log", "x")
    assert list(outside.iterdir()) == []
    (tmp_path / "link-state").symlink_to(outside)
    with pytest.raises(UnsafeStatePath):
        FsRunStore(tmp_path / "link-state")


def test_a_missing_scheduler_command_is_a_controlled_failure(tmp_path: Path) -> None:
    from chores.adapters.scheduler import (
        SchedulerInstallFailed,
        SystemdInstaller,
        _run_subprocess,
    )

    with pytest.raises(SchedulerInstallFailed, match="cannot run"):
        _run_subprocess(["/definitely/not/launchctl", "print"])

    def missing(argv: list[str]) -> int:
        raise SchedulerInstallFailed(f"cannot run {argv[0]}: not found")

    launchd = LaunchdInstaller(home=tmp_path / "mac", uid=1, run=missing)
    with pytest.raises(SchedulerInstallFailed, match="cannot run"):
        launchd.install(interval_sec=60)
    assert launchd.installed() is False  # the written plist was removed
    systemd = SystemdInstaller(home=tmp_path / "linux", run=missing)
    with pytest.raises(SchedulerInstallFailed, match="cannot run"):
        systemd.install(interval_sec=60)
    assert systemd.installed() is False
    assert not (systemd.unit_dir / "chores-tick.service").exists()


# --- Copilot round 11 (PR #290) --------------------------------------------


def test_no_state_file_is_ever_read_or_written_through_a_symlink(
    tmp_path: Path,
) -> None:
    from chores.adapters.fs_store import (
        FsRunStore,
        InvalidArtifactName,
        UnsafeStatePath,
    )

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "run.json").write_text("{}")
    store = FsRunStore(tmp_path / "s")
    run_id = "tidy-20260302T100000Z-ab12"
    record = RunRecord.pending(
        run_id=run_id, chore="tidy", kind=Kind.COMMAND, definition_rev="r", started=T0
    )
    store.write_record(record)
    run_dir = store.runs / "tidy" / run_id
    # enumeration never follows a symlinked chore dir, run dir or record
    (store.runs / "linked-chore").symlink_to(outside)
    (store.runs / "tidy" / "linked-run").symlink_to(outside)
    (store.runs / "tidy" / "tidy-20260302T110000Z-ab12").mkdir()
    (store.runs / "tidy" / "tidy-20260302T110000Z-ab12" / "run.json").symlink_to(
        outside / "run.json"
    )
    assert [r.run_id for r in store.records()] == [run_id]
    # artifacts, the ledger and the sentries are written no-follow
    target = outside / "leak.log"
    (run_dir / "stdout.log").symlink_to(target)
    with pytest.raises(UnsafeStatePath):
        store.append_artifact(run_id, "stdout.log", "secret\n")
    assert not target.exists()
    with pytest.raises(UnsafeStatePath):
        store.read_artifact(run_id, "stdout.log")
    with pytest.raises(InvalidArtifactName):
        store.append_artifact(run_id, "../escape", "x")
    (store.root / "ledger.ndjson").symlink_to(outside / "ledger")
    with pytest.raises(UnsafeStatePath):
        store.append_ledger({"a": 1})
    assert not (outside / "ledger").exists()
    (store.root / "PAUSED").symlink_to(outside / "paused")
    with pytest.raises(UnsafeStatePath):
        store.pause("x")
    with pytest.raises(UnsafeStatePath):
        store.paused()
    assert store.run_dir_bytes(run_id) > 0  # counts real files only


# --- Copilot round 12 (PR #290) --------------------------------------------


def test_admission_and_the_pending_write_share_one_chore_lock(tmp_path: Path) -> None:
    """The overlap check and the PENDING write happen under the per-chore
    lock, so a concurrent runner of the same chore serialises behind it and
    then sees the young PENDING record as live."""
    h = FullHarness(tmp_path, chores={"tidy": COMMAND})
    run_chore("tidy", h.deps().as_run_deps())
    events = h.store.events
    assert events[:3] == ["lock tidy", "write PENDING", "unlock tidy"]
    dry = FullHarness(tmp_path / "d", chores={"tidy": COMMAND})
    run_chore("tidy", dry.deps().as_run_deps(), dry_run=True)
    assert dry.store.events == []  # a dry run reserves nothing


def test_fs_chore_lock_lives_in_the_chore_dir_and_is_no_follow(tmp_path: Path) -> None:
    from chores.adapters.fs_store import FsRunStore, UnsafeStatePath

    store = FsRunStore(tmp_path / "s")
    with store.chore_lock("tidy"):
        assert (store.runs / "tidy" / "admission.lock").is_file()
    outside = tmp_path / "outside"
    outside.mkdir()
    (store.runs / "evil").mkdir()
    (store.runs / "evil" / "admission.lock").symlink_to(outside / "lock")
    with pytest.raises(UnsafeStatePath):
        with store.chore_lock("evil"):
            pass
    assert not (outside / "lock").exists()


def test_home_pointer_and_spawn_log_are_written_no_follow(tmp_path: Path) -> None:
    from chores.adapters.fs_store import UnsafeStatePath
    from chores.application.paths import Paths
    from chores.cli.wiring import _launch_factory, remember_home

    outside = tmp_path / "outside"
    outside.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    (state / "home").symlink_to(outside / "pointer")
    paths = Paths(str(tmp_path / "home"), str(state), str(tmp_path / "data"))
    with pytest.raises(UnsafeStatePath):
        remember_home(paths)
    assert not (outside / "pointer").exists()
    (state / "spawn.log").symlink_to(outside / "spawn")
    with pytest.raises(UnsafeStatePath):
        _launch_factory(state)("tidy")
    assert not (outside / "spawn").exists()


def test_systemd_install_fails_when_daemon_reload_fails(tmp_path: Path) -> None:
    from chores.adapters.scheduler import SchedulerInstallFailed, SystemdInstaller

    calls: list[list[str]] = []

    def reload_fails(argv: list[str]) -> int:
        calls.append(argv)
        return 1 if "daemon-reload" in argv and len(calls) == 1 else 0

    inst = SystemdInstaller(home=tmp_path, run=reload_fails)
    with pytest.raises(SchedulerInstallFailed, match="daemon-reload"):
        inst.install(interval_sec=60)
    assert inst.installed() is False
    assert not (inst.unit_dir / "chores-tick.service").exists()
    assert calls[-1] == ["systemctl", "--user", "daemon-reload"]  # reloaded again


# --- Copilot round 13 (PR #290) --------------------------------------------


def test_is_under_treats_the_filesystem_root_as_containing_everything() -> None:
    from chores.domain.chore import is_under

    assert is_under("/home/x", "/") and is_under("/", "/")
    assert not is_under("/", "/home")
    assert is_under("/home/x/y", "/home/x/") and not is_under("/home/xy", "/home/x")


def test_failed_install_unloads_what_it_loaded(tmp_path: Path) -> None:
    from chores.adapters.scheduler import SchedulerInstallFailed, SystemdInstaller

    calls: list[list[str]] = []

    def enable_fails(argv: list[str]) -> int:
        calls.append(argv)
        return 1 if "bootstrap" in argv or "enable" in argv else 0

    launchd = LaunchdInstaller(home=tmp_path / "mac", uid=1, run=enable_fails)
    with pytest.raises(SchedulerInstallFailed, match="booted out"):
        launchd.install(interval_sec=60)
    assert calls[-1][:2] == ["launchctl", "bootout"] and not launchd.installed()
    calls.clear()
    systemd = SystemdInstaller(home=tmp_path / "linux", run=enable_fails)
    with pytest.raises(SchedulerInstallFailed, match="disabled and removed"):
        systemd.install(interval_sec=60)
    assert ["systemctl", "--user", "disable", "--now", "chores-tick.timer"] in calls
    assert calls[-1] == ["systemctl", "--user", "daemon-reload"]
    assert not systemd.installed()


def test_install_persists_the_pointer_first_and_rolls_it_back(tmp_path: Path) -> None:
    from dataclasses import replace

    from click.testing import CliRunner

    from chores.cli.main import main

    h = FullHarness(tmp_path, chores={"tidy": COMMAND})
    state = Path(h.paths.state_dir)
    state.mkdir(parents=True, exist_ok=True)
    (state / "home").symlink_to(tmp_path / "elsewhere")
    calls: list[list[str]] = []
    inst = LaunchdInstaller(
        home=tmp_path / "h", uid=7, run=lambda argv: calls.append(argv) or 0
    )
    deps = replace(h.deps(), installer=inst, scheduler_installed=inst.installed)
    r = CliRunner().invoke(main, ["install"], obj=deps)
    assert r.exit_code == 1 and "symlink" in r.output
    assert calls == [] and not inst.installed()  # refused before the OS job
    (state / "home").unlink()
    failing = LaunchdInstaller(home=tmp_path / "h2", uid=7, run=lambda argv: 1)
    deps = replace(h.deps(), installer=failing, scheduler_installed=failing.installed)
    r = CliRunner().invoke(main, ["install"], obj=deps)
    assert r.exit_code == 1 and not (state / "home").exists()  # pointer rolled back


# --- Copilot round 14 (PR #290) --------------------------------------------


def test_read_nofollow_is_one_descriptor(tmp_path: Path) -> None:
    from chores.adapters.fs_store import UnsafeStatePath, read_nofollow

    assert read_nofollow(tmp_path / "missing") is None
    (tmp_path / "f").write_text("x")
    assert read_nofollow(tmp_path / "f") == "x"
    (tmp_path / "d").mkdir()
    assert read_nofollow(tmp_path / "d") is None  # not a regular file
    (tmp_path / "l").symlink_to(tmp_path / "f")
    with pytest.raises(UnsafeStatePath):
        read_nofollow(tmp_path / "l")  # ELOOP from the kernel, never followed


def test_kill_marker_is_read_no_follow(tmp_path: Path) -> None:
    from chores.adapters.fs_store import FsRunStore, UnsafeStatePath

    store = FsRunStore(tmp_path / "s")
    run_id = "tidy-20260302T100000Z-ab12"
    store.write_record(
        RunRecord.pending(
            run_id=run_id,
            chore="tidy",
            kind=Kind.COMMAND,
            definition_rev="r",
            started=T0,
        )
    )
    assert store.kill_requested(run_id) is False
    (store.runs / "tidy" / run_id / "KILL").symlink_to(tmp_path / "s" / "ledger.ndjson")
    with pytest.raises(UnsafeStatePath):
        store.kill_requested(run_id)  # a planted link never counts as a kill


def test_claude_response_without_a_result_string_is_a_backend_error() -> None:
    import json

    from chores.adapters.claude_cli import ClaudeCliAgent
    from chores.ports.agent import AgentTask

    process = FakeProcess(stdout=json.dumps({}))
    agent = ClaudeCliAgent(process, binary="claude")
    with pytest.raises(BackendError, match="no result string"):
        agent.run(
            AgentTask(
                body="x",
                model="m",
                cwd="/tmp",
                allowed_tools=frozenset(),
                max_turns=1,
                timeout_sec=1.0,
                env={},
                kill_grace_sec=1,
            ),
            on_start=lambda _identity: None,
        )


def test_prompt_body_is_verbatim_and_bad_utf8_is_reported(tmp_path: Path) -> None:
    from chores.adapters.definitions import DefinitionsLoader, split_front_matter

    _data, body = split_front_matter("---\nname: p\n---\n\n  keep me  \n\n")
    assert body == "\n  keep me  \n\n"
    home = tmp_path / "home"
    (home / "chores").mkdir(parents=True)
    (home / "chores" / "bad.md").write_bytes(b"---\nname: bad\n---\n\xff\xfe")
    (home / "backends.yaml").write_bytes(b"\xff")
    (home / "config.yaml").write_bytes(b"\xff")
    defs = DefinitionsLoader(home, revision_reader=lambda _: "r").load()
    assert [i.name for i in defs.invalid] == ["bad"]
    assert any("backends.yaml" in e for e in defs.errors)
    assert defs.config_error is not None


def test_runs_since_zero_is_a_boundary(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from chores.cli.main import main

    h = FullHarness(tmp_path, chores={"tidy": COMMAND})
    old = RunRecord.pending(
        run_id="tidy-a",
        chore="tidy",
        kind=Kind.COMMAND,
        definition_rev="r",
        started=h.clock.now_utc() - timedelta(hours=1),
    )
    h.store.write_record(old)
    r = CliRunner().invoke(main, ["runs", "--since", "0"], obj=h.deps())
    assert r.exit_code == 0 and "tidy-a" not in r.output
    r = CliRunner().invoke(main, ["runs", "--since", "2"], obj=h.deps())
    assert "tidy-a" in r.output


# --- Copilot round 15 (PR #290) --------------------------------------------


def test_validate_ignores_runtime_warnings_but_fails_on_problems(
    tmp_path: Path,
) -> None:
    from click.testing import CliRunner

    from chores.cli.main import main

    h = FullHarness(tmp_path, chores={"tidy": COMMAND})
    h.store.mark_tick(TickMark(at=h.clock.now_utc(), ledger_rows=5))  # "shrank"
    view = status(h.deps())
    assert any("shrank" in w for w in view.warnings) and view.problems == []
    r = CliRunner().invoke(main, ["validate"], obj=h.deps())
    assert r.exit_code == 0 and "ok: 1 chore(s)" in r.output
    (tmp_path / "home" / "backends.yaml").write_text(
        "backends:\n  metered:\n    type: openai-compat\n    model: m\n"
        "    base_url: https://gw\n    ceiling: {usd: 1.0}\n"
    )
    r = CliRunner().invoke(main, ["validate"], obj=h.deps())
    assert r.exit_code == 1 and "no price table" in r.output


def test_unwritable_unit_paths_are_a_controlled_install_failure(
    tmp_path: Path,
) -> None:
    from chores.adapters.scheduler import SchedulerInstallFailed, SystemdInstaller

    blocker = tmp_path / "mac" / "Library"
    blocker.parent.mkdir()
    blocker.write_text("a file where a directory must go")
    launchd = LaunchdInstaller(home=tmp_path / "mac", uid=1, run=lambda a: 0)
    with pytest.raises(SchedulerInstallFailed, match="cannot write"):
        launchd.install(interval_sec=60)
    blocker = tmp_path / "linux" / ".config"
    blocker.parent.mkdir()
    blocker.write_text("same")
    systemd = SystemdInstaller(home=tmp_path / "linux", run=lambda a: 0)
    with pytest.raises(SchedulerInstallFailed, match="cannot write"):
        systemd.install(interval_sec=60)


# --- Copilot round 17 (PR #290) --------------------------------------------


def test_every_run_leaves_all_five_artifacts(tmp_path: Path) -> None:
    """Design: a complete, separated record -- an empty stream is an empty
    file, never a missing one (on the real store and the fake alike)."""
    from chores.adapters.fs_store import FsRunStore

    expected = {
        "definition.md",
        "transcript.jsonl",
        "stdout.log",
        "stderr.log",
        "errors.log",
    }
    h = FullHarness(tmp_path, chores={"tidy": COMMAND})
    r = run_chore("tidy", h.deps().as_run_deps()).record
    assert r and r.status is RunStatus.SUCCEEDED
    assert set(h.store.artifacts(r.run_id)) == expected
    real = FullHarness(tmp_path / "real", chores={"tidy": COMMAND})
    real.store = FsRunStore(tmp_path / "real" / "state")  # type: ignore[assignment]
    r = run_chore("tidy", real.deps().as_run_deps()).record
    assert r and set(real.store.artifacts(r.run_id)) == expected
    assert real.store.read_artifact(r.run_id, "errors.log") == ""


def test_a_manual_run_slipping_in_after_the_ticks_admission_is_skipped(
    tmp_path: Path,
) -> None:
    """The tick's admission is advisory: the runner it launches is `chores
    run`, which re-admits under the per-chore lock. A manual run that lands
    between the tick's admit and the child's admission makes the child
    SKIPPED_OVERLAP, so two runs never execute."""
    hourly = COMMAND.replace("'* * * * *'", "'0 * * * *'")
    h = FullHarness(tmp_path, chores={"tidy": hourly})
    h.store.mark_tick(
        TickMark(at=h.clock.now_utc() - timedelta(seconds=60), ledger_rows=0)
    )
    tick(h.deps().as_tick_deps())
    assert h.launched == ["tidy"]
    manual = RunRecord.pending(
        run_id="tidy-manual",
        chore="tidy",
        kind=Kind.COMMAND,
        definition_rev="r",
        started=h.clock.now_utc(),
    )
    h.store.write_record(manual)  # the manual `chores run` wins the lock first
    child = run_chore("tidy", h.deps().as_run_deps()).record  # the tick's child
    assert child and child.status is RunStatus.SKIPPED_OVERLAP
    assert "tidy-manual" in (child.reason or "")


# --- Copilot round 18 (PR #290) --------------------------------------------


def test_unit_files_are_written_no_follow(tmp_path: Path) -> None:
    from chores.adapters.scheduler import SchedulerInstallFailed, SystemdInstaller

    outside = tmp_path / "outside"
    outside.mkdir()
    agents = tmp_path / "mac" / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    (agents / "com.tds.chores.tick.plist").symlink_to(outside / "plist")
    launchd = LaunchdInstaller(home=tmp_path / "mac", uid=1, run=lambda a: 0)
    with pytest.raises(SchedulerInstallFailed, match="symlink"):
        launchd.install(interval_sec=60)
    assert not (outside / "plist").exists()
    units = tmp_path / "linux" / ".config" / "systemd" / "user"
    units.mkdir(parents=True)
    (units / "chores-tick.timer").symlink_to(outside / "timer")
    systemd = SystemdInstaller(home=tmp_path / "linux", run=lambda a: 0)
    with pytest.raises(SchedulerInstallFailed, match="symlink"):
        systemd.install(interval_sec=60)
    assert not (outside / "timer").exists()
    assert not (units / "chores-tick.service").exists()  # cleaned up


def test_state_and_definitions_roots_may_not_contain_each_other(tmp_path: Path) -> None:
    from chores.application.paths import OverlappingRoots, Paths

    with pytest.raises(OverlappingRoots, match="definitions"):
        Paths(
            str(tmp_path / "cfg" / "chores"), str(tmp_path / "cfg"), str(tmp_path / "d")
        )
    with pytest.raises(OverlappingRoots):
        Paths(str(tmp_path / "s" / "home"), str(tmp_path / "s"), str(tmp_path / "d"))
    Paths(
        str(tmp_path / "h"), str(tmp_path / "s"), str(tmp_path / "d")
    )  # distinct: fine


# --- Copilot round 19 (PR #290) --------------------------------------------


def test_every_outcome_record_carries_the_five_artifacts(tmp_path: Path) -> None:
    """A refusal, MISSED or INVALID record is a run directory like any other:
    all five artifacts exist (empty streams are empty files) and errors.log
    carries the reason."""
    from chores.adapters.fs_store import FsRunStore

    h = FullHarness(tmp_path, chores={"tidy": COMMAND})
    h.store = FsRunStore(tmp_path / "state")  # type: ignore[assignment]
    h.store.pause("maintenance")
    r = run_chore("tidy", h.deps().as_run_deps()).record
    assert r and r.status is RunStatus.SKIPPED_PAUSED
    assert set(h.store.artifacts(r.run_id)) == set(ARTIFACTS)
    assert "maintenance" in h.store.read_artifact(r.run_id, "errors.log")


def test_systemd_service_runs_a_plain_shell_so_the_unit_path_holds(
    tmp_path: Path,
) -> None:
    from chores.adapters.scheduler import SystemdInstaller

    inst = SystemdInstaller(home=tmp_path, run=lambda a: 0)
    inst.install(interval_sec=60)
    service = (inst.unit_dir / "chores-tick.service").read_text()
    exec_line = next(line for line in service.splitlines() if "ExecStart" in line)
    assert exec_line == "ExecStart=/bin/bash -c 'exec chores tick'"
    assert "-l" not in exec_line  # a login shell could rebuild PATH


def test_a_failed_reinstall_never_leaves_the_old_timer_loaded(tmp_path: Path) -> None:
    """Whatever fails during a reinstall (here: the reload), the rollback
    stops and disables the timer before the unit files go, so nothing
    loaded outlives files that are gone."""
    from chores.adapters.scheduler import SchedulerInstallFailed, SystemdInstaller

    calls: list[list[str]] = []

    def reload_fails_once(argv: list[str]) -> int:
        calls.append(argv)
        reloads = sum(1 for c in calls if "daemon-reload" in c)
        return 1 if "daemon-reload" in argv and reloads == 1 else 0

    inst = SystemdInstaller(home=tmp_path, run=reload_fails_once)
    with pytest.raises(SchedulerInstallFailed, match="daemon-reload"):
        inst.install(interval_sec=60)
    assert ["systemctl", "--user", "disable", "--now", "chores-tick.timer"] in calls
    assert inst.installed() is False
    launchd_calls: list[list[str]] = []

    def launchctl_missing(argv: list[str]) -> int:
        launchd_calls.append(argv)
        raise SchedulerInstallFailed("cannot run launchctl")

    mac = LaunchdInstaller(home=tmp_path / "mac", uid=1, run=launchctl_missing)
    with pytest.raises(SchedulerInstallFailed):
        mac.install(interval_sec=60)
    assert mac.installed() is False


# --- Copilot round 20 (PR #290) --------------------------------------------


def test_a_refused_unit_write_leaves_what_it_found(tmp_path: Path) -> None:
    """An installer removes only what this invocation wrote. A path whose
    no-follow write was refused (a symlink someone planted, or a unit a
    previous install left) is preserved, and when nothing was written nothing
    is disabled either."""
    from chores.adapters.scheduler import SchedulerInstallFailed, SystemdInstaller

    outside = tmp_path / "outside"
    outside.mkdir()
    agents = tmp_path / "mac" / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    plist = agents / "com.tds.chores.tick.plist"
    plist.symlink_to(outside / "plist")
    mac_calls: list[list[str]] = []
    launchd = LaunchdInstaller(
        home=tmp_path / "mac", uid=1, run=lambda a: mac_calls.append(a) or 0
    )
    with pytest.raises(SchedulerInstallFailed, match="symlink"):
        launchd.install(interval_sec=60)
    assert plist.is_symlink() and mac_calls == []  # preserved, nothing booted out
    units = tmp_path / "linux" / ".config" / "systemd" / "user"
    units.mkdir(parents=True)
    service = units / "chores-tick.service"
    service.symlink_to(outside / "service")
    calls: list[list[str]] = []
    systemd = SystemdInstaller(
        home=tmp_path / "linux", run=lambda a: calls.append(a) or 0
    )
    with pytest.raises(SchedulerInstallFailed, match="symlink"):
        systemd.install(interval_sec=60)
    assert service.is_symlink() and calls == []  # first write refused: untouched
    assert not systemd.timer.exists()
    service.unlink()
    systemd.timer.symlink_to(outside / "timer")
    with pytest.raises(SchedulerInstallFailed, match="symlink"):
        systemd.install(interval_sec=60)
    assert systemd.timer.is_symlink()  # the refused path is preserved
    assert not service.exists()  # the unit this invocation wrote is gone
    assert ["systemctl", "--user", "disable", "--now", "chores-tick.timer"] in calls


def test_outcome_artifacts_go_through_the_size_cap(tmp_path: Path) -> None:
    """A tick-written outcome's errors.log and definition snapshot are bounded
    by max_run_dir_bytes like every run artifact: a refusal recorded on every
    tick cannot fill the state volume."""
    from chores.adapters.fs_store import FsRunStore
    from chores.application.context import write_outcome

    store = FsRunStore(tmp_path / "state")
    record = write_outcome(
        store,
        run_id="tidy-20260917T000000Z-abcd",
        chore="tidy",
        kind=Kind.COMMAND,
        definition_rev="r1",
        status=RunStatus.SKIPPED_PAUSED,
        reason="x" * 10_000,
        at=T0,
        max_bytes=2_000,
        definition="y" * 10_000,
    )
    assert record.status is RunStatus.SKIPPED_PAUSED
    assert set(store.artifacts(record.run_id)) == set(ARTIFACTS)
    assert store.read_artifact(record.run_id, "errors.log") == ""
    assert store.read_artifact(record.run_id, "definition.md") == ""
    assert store.ledger_count() == 1
    small = write_outcome(
        store,
        run_id="tidy-20260917T000001Z-abcd",
        chore="tidy",
        kind=Kind.COMMAND,
        definition_rev="r1",
        status=RunStatus.SKIPPED_PAUSED,
        reason="paused",
        at=T0,
        max_bytes=2_000,
    )
    assert store.read_artifact(small.run_id, "errors.log") == "paused\n"


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


def test_notify_on_members_must_be_status_names() -> None:
    from chores.domain.chore import InvalidChore

    from .test_chore import PROMPT as CHORE_MAPPING

    for bad in ([{}], [None], [["SUCCEEDED"]], [3]):
        with pytest.raises(InvalidChore, match="notify_on"):
            Chore.from_mapping({**CHORE_MAPPING, "notify_on": bad}, body="x")
