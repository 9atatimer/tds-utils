"""The run use case (CHORES.DESIGN.md Subsystem 3) against fakes."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from chores.adapters.definitions import DefinitionsLoader
from chores.application.paths import Paths
from chores.application.run import RunDeps, run_chore
from chores.application.tick import tick
from chores.domain.kinds import Kind
from chores.domain.run import RunRecord, RunStatus
from chores.ports.errors import BackendError, BackendTimeout, ProcessError, Unreachable
from chores.ports.store import ARTIFACTS, TickMark

from ._fakes import (
    FakeAgent,
    FakeClock,
    FakeCompletion,
    FakeNetwork,
    FakeNotifier,
    FakePower,
    FakeProcess,
    FakeRunStore,
    FakeSecrets,
    FakeWorkspaces,
)
from ._harness import (
    AGENT,
    COMMAND,
    LOCAL,
    PROMPT,
    SECRET,
    FakeCatalog,
    FullHarness,
    write_home,
)

T0 = datetime(2026, 3, 2, 10, 0)


class Harness:
    def __init__(
        self,
        tmp_path: Path,
        *,
        chores: Mapping[str, str],
        config: str = "",
        **fakes: object,
    ) -> None:
        home = tmp_path / "home"
        write_home(home, chores=chores, config=config)
        self.store = FakeRunStore()
        self.clock = FakeClock(T0)
        self.process = FakeProcess(**fakes.get("process", {}))  # type: ignore[arg-type]
        self.secrets = FakeSecrets(
            {"op://v/gw/password": SECRET, "op://v/other/credential": "other-secret"}
        )
        self.power = FakePower()
        self.network = FakeNetwork()
        self.notifier = FakeNotifier()
        self.workspaces = FakeWorkspaces()
        self.catalog = FakeCatalog(
            completion=fakes.get("completion"), agent=fakes.get("agent")
        )  # type: ignore[arg-type]
        self.paths = Paths(
            chores_home=str(home),
            state_dir=str(tmp_path / "state"),
            data_dir=str(tmp_path / "data"),
        )
        self.definitions = DefinitionsLoader(home, revision_reader=lambda _: "rev1")

    def deps(self) -> RunDeps:
        return RunDeps(
            definitions=self.definitions,
            catalog_for=lambda d: self.catalog,
            store=self.store,
            clock=self.clock,
            process=self.process,
            secrets=self.secrets,
            power=self.power,
            network=self.network,
            notifier=self.notifier,
            workspaces=self.workspaces,
            paths=self.paths,
            inherited_env={
                "PATH": "/usr/bin",
                "HOME": "/home/t",
                "LANG": "C",
                "JUNK": "no",
            },
            run_id_suffix=lambda: "ab12",
        )


def test_prompt_run_succeeds_with_full_record(tmp_path: Path) -> None:
    """Given a prompt chore, When run, Then SUCCEEDED with usage, transcript, ledger."""
    h = Harness(tmp_path, chores={"brand": PROMPT})
    out = run_chore("brand", h.deps())
    r = out.record
    assert r is not None and r.status is RunStatus.SUCCEEDED
    assert r.run_id == "brand-20260302T100000Z-ab12" and r.definition_rev == "rev1"
    assert r.backend == "gw" and r.model == "m" and r.usage and r.usage.tokens == 15
    assert h.store.read_record(r.run_id) == r
    assert (
        h.store.ledger_count() == 1
        and h.store.ledger_rows()[0]["status"] == "SUCCEEDED"
    )
    transcript = [
        json.loads(line)
        for line in h.store.read_artifact(r.run_id, "transcript.jsonl").splitlines()
    ]
    assert (
        transcript[0]["role"] == "user" and transcript[0]["content"] == "Summarize.\n"
    )
    assert transcript[1]["role"] == "assistant" and transcript[1]["content"] == "ok"
    assert h.store.read_artifact(r.run_id, "definition.md").startswith(
        "---\nname: brand"
    )
    assert h.catalog.credentials == [SECRET]
    assert h.store.notifications() == []


def test_secret_values_never_reach_the_store(tmp_path: Path) -> None:
    """Given a backend that echoes the credential, Then every artifact is redacted."""
    h = Harness(
        tmp_path,
        chores={"brand": PROMPT},
        completion=FakeCompletion(text=f"key={SECRET} json={json.dumps(SECRET)[1:-1]}"),
    )
    out = run_chore("brand", h.deps())
    assert out.record and out.record.status is RunStatus.SUCCEEDED
    for name in h.store.artifacts(out.record.run_id):
        assert SECRET not in h.store.read_artifact(out.record.run_id, name)
        assert "other-secret" not in h.store.read_artifact(out.record.run_id, name)
    assert "[REDACTED]" in h.store.read_artifact(out.record.run_id, "transcript.jsonl")


def test_command_run_builds_explicit_env_and_captures_streams(tmp_path: Path) -> None:
    h = Harness(
        tmp_path,
        chores={"tidy": COMMAND},
        process={"stdout": "hi\n", "stderr": "warn\n"},
    )
    out = run_chore("tidy", h.deps())
    r = out.record
    assert r and r.status is RunStatus.SUCCEEDED and r.exit_code == 0 and r.pid is None
    req = h.process.requests[0]
    assert list(req.argv) == ["echo", "hi"] and req.cwd == "/data/workspaces/tidy"
    assert (
        "JUNK" not in req.env
        and req.env["PATH"] == "/usr/bin"
        and req.env["HOME"] == "/home/t"
    )
    assert req.env["CHORES_RUN_ID"] == r.run_id and req.env["CHORES_CHORE"] == "tidy"
    assert (
        req.env["CHORES_BUDGET_SECONDS"] == "5"
        and "CHORES_BUDGET_TOKENS" not in req.env
    )
    assert h.store.read_artifact(r.run_id, "stdout.log") == "hi\n"
    assert h.store.read_artifact(r.run_id, "stderr.log") == "warn\n"


def test_agent_run_passes_tools_turns_and_secret_names(tmp_path: Path) -> None:
    h = Harness(tmp_path, chores={"rev": AGENT})
    out = run_chore("rev", h.deps())
    assert out.record and out.record.status is RunStatus.SUCCEEDED
    task = h.catalog._agent.tasks[0]
    assert task.allowed_tools == frozenset({"Read", "Grep"}) and task.max_turns == 5
    assert (
        task.env["CHORES_BUDGET_TURNS"] == "5" and task.env["CHORES_SECRET_NAMES"] == ""
    )
    assert out.record.usage and out.record.usage.turns == 3


@pytest.mark.parametrize(
    ("fake", "status", "word"),
    [
        (
            {"completion": FakeCompletion(tokens_in=5000, tokens_out=1)},
            RunStatus.BUDGET_EXCEEDED,
            "tokens",
        ),
        (
            {"completion": FakeCompletion(error=Unreachable("down"))},
            RunStatus.OFFLINE,
            "down",
        ),
        (
            {"completion": FakeCompletion(error=BackendTimeout("slow"))},
            RunStatus.TIMED_OUT,
            "slow",
        ),
    ],
)
def test_prompt_failures_map_to_statuses(
    tmp_path: Path, fake: Mapping[str, object], status: RunStatus, word: str
) -> None:
    h = Harness(tmp_path, chores={"brand": PROMPT}, **fake)
    out = run_chore("brand", h.deps())
    assert (
        out.record and out.record.status is status and word in (out.record.reason or "")
    )
    assert h.store.ledger_rows()[0]["status"] == status.value
    assert [n.level for n in h.store.notifications()] == [
        "alert" if status is RunStatus.BUDGET_EXCEEDED else "info"
    ]


def test_unreachable_local_backend_is_failed_not_offline(tmp_path: Path) -> None:
    h = Harness(
        tmp_path,
        chores={"loc": LOCAL},
        completion=FakeCompletion(error=Unreachable("no ollama")),
    )
    out = run_chore("loc", h.deps())
    assert out.record and out.record.status is RunStatus.FAILED


def test_command_timeout_and_nonzero_exit(tmp_path: Path) -> None:
    h = Harness(
        tmp_path, chores={"tidy": COMMAND}, process={"timed_out": True, "exit_code": -9}
    )
    assert (run_chore("tidy", h.deps()).record or None).status is RunStatus.TIMED_OUT  # type: ignore[union-attr]
    h2 = Harness(
        tmp_path / "b",
        chores={"tidy": COMMAND},
        process={"exit_code": 2, "stderr": "bad"},
    )
    r = run_chore("tidy", h2.deps()).record
    assert r and r.status is RunStatus.FAILED and "exit 2" in (r.reason or "")


def test_kill_marker_records_killed(tmp_path: Path) -> None:
    h = Harness(tmp_path, chores={"tidy": COMMAND}, process={"exit_code": -15})
    h.store.request_kill("tidy-20260302T100000Z-ab12")
    r = run_chore("tidy", h.deps()).record
    assert r and r.status is RunStatus.KILLED


def test_secret_unavailable_fails_naming_the_reference_not_the_value(
    tmp_path: Path,
) -> None:
    h = Harness(tmp_path, chores={"brand": PROMPT})
    h.secrets.values.pop("op://v/other/credential")
    r = run_chore("brand", h.deps()).record
    assert (
        r
        and r.status is RunStatus.FAILED
        and "op://v/other/credential" in (r.reason or "")
    )
    assert h.catalog.credentials == []


def test_paused_skips_even_with_force_and_writes_a_record(tmp_path: Path) -> None:
    h = Harness(tmp_path, chores={"brand": PROMPT})
    h.store.pause("flight")
    out = run_chore("brand", h.deps(), force=True)
    assert (
        out.record
        and out.record.status is RunStatus.SKIPPED_PAUSED
        and "flight" in (out.record.reason or "")
    )
    assert h.catalog.credentials == [] and h.store.ledger_count() == 1


def test_offline_probe_skips_network_chore_and_force_lifts_it(tmp_path: Path) -> None:
    h = Harness(tmp_path, chores={"brand": PROMPT})
    h.network.online = False
    assert (
        run_chore("brand", h.deps()).record or None
    ).status is RunStatus.SKIPPED_OFFLINE  # type: ignore[union-attr]
    assert h.network.probed == ["https://gw.example"]
    assert (
        run_chore("brand", h.deps(), force=True).record or None
    ).status is RunStatus.SUCCEEDED  # type: ignore[union-attr]


def test_ceiling_refusal_writes_skipped_ceiling(tmp_path: Path) -> None:
    h = Harness(tmp_path, chores={"brand": PROMPT})
    for _ in range(10):
        h.clock.advance(60)
        run_chore("brand", h.deps())  # 0.001 usd each; tokens 15 each
    h.store.append_ledger(
        {
            **h.store.ledger_rows()[0],
            "run_id": "x",
            "usd": 0.95,
            "started": T0.isoformat(),
        }
    )
    r = run_chore("brand", h.deps()).record
    assert (
        r
        and r.status is RunStatus.SKIPPED_CEILING
        and "backend usd" in (r.reason or "")
    )


def test_breaker_pauses_chore_after_threshold_and_alerts(tmp_path: Path) -> None:
    h = Harness(
        tmp_path,
        chores={"tidy": COMMAND},
        config="failure_threshold: 2\n",
        process={"exit_code": 1},
    )
    run_chore("tidy", h.deps())
    h.clock.advance(60)
    assert h.store.chore_paused("tidy") is None
    run_chore("tidy", h.deps())
    h.clock.advance(60)
    assert h.store.chore_paused("tidy") is not None
    assert any(
        n.level == "alert" and "paused" in n.text for n in h.store.notifications()
    )
    assert any("paused" in text for _, text in h.notifier.alerts)
    r = run_chore("tidy", h.deps()).record
    assert r and r.status is RunStatus.SKIPPED_PAUSED


def test_dry_run_plans_without_records_or_secrets(tmp_path: Path) -> None:
    h = Harness(tmp_path, chores={"brand": PROMPT})
    out = run_chore("brand", h.deps(), dry_run=True)
    assert out.record is None and out.plan is not None
    assert (
        out.plan.backend == "gw"
        and out.plan.model == "m"
        and "API_KEY" in out.plan.secret_names
    )
    assert SECRET not in str(out.plan) and h.secrets.resolved == []
    assert h.store.records() == [] and out.plan.admission == "ADMIT"


def test_invalid_or_unknown_chore_is_reported(tmp_path: Path) -> None:
    h = Harness(tmp_path, chores={"bad": "---\nname: bad\nkind: prompt\n---\n"})
    out = run_chore("bad", h.deps())
    assert (
        out.record
        and out.record.status is RunStatus.INVALID
        and "schedule" in (out.record.reason or "")
    )
    assert run_chore("nope", h.deps()).record is None


def test_overlap_skips_when_a_live_run_exists(tmp_path: Path) -> None:
    h = Harness(tmp_path, chores={"brand": PROMPT})
    first = run_chore("brand", h.deps()).record
    assert first
    running = first.__class__.pending(
        run_id="brand-x", chore="brand", kind=first.kind, definition_rev="r", started=T0
    ).start(pid=555, pgid=555, process_start=1.0)
    h.store.write_record(running)
    h.process.alive_pids.add(555)
    h.clock.advance(60)
    r = run_chore("brand", h.deps()).record
    assert r and r.status is RunStatus.SKIPPED_OVERLAP and "brand-x" in (r.reason or "")
    assert r.started == T0 + timedelta(seconds=60)


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


def test_definition_snapshot_is_redacted(tmp_path: Path) -> None:
    """Given a definition body that pastes the credential literally, Then the
    snapshot carries [REDACTED]."""
    leaky = PROMPT.replace("Summarize.", f"Summarize. key={SECRET}")
    h = FullHarness(tmp_path, chores={"brand": leaky})
    r = run_chore("brand", h.deps().as_run_deps()).record
    assert r is not None
    snapshot = h.store.read_artifact(r.run_id, "definition.md")
    assert SECRET not in snapshot and "[REDACTED]" in snapshot


def test_agent_spawn_failure_records_failed(tmp_path: Path) -> None:
    class SpawnFails(FakeAgent):
        def run(self, task, *, on_start):  # type: ignore[no-untyped-def]
            raise ProcessError("could not start 'claude'")

    h = FullHarness(tmp_path, chores={"rev": AGENT}, agent=SpawnFails())
    r = run_chore("rev", h.deps().as_run_deps()).record
    assert r and r.status is RunStatus.FAILED and "could not start" in (r.reason or "")


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


def test_manual_run_of_a_bad_stem_definition_records_invalid(tmp_path: Path) -> None:
    from chores.adapters.fs_store import FsRunStore

    h = FullHarness(tmp_path, chores={"tidy": COMMAND})
    (tmp_path / "home" / "chores" / "foo.bar.md").write_text(
        "---\nname: foo.bar\nkind: command\n---\n"
    )
    h.store = FsRunStore(tmp_path / "state")  # type: ignore[assignment]
    r = run_chore("foo.bar", h.deps().as_run_deps()).record
    assert r is not None and r.status is RunStatus.INVALID
    assert r.chore == "INVALID-foo-bar" and h.store.read_record(r.run_id) == r


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


def test_output_dropped_by_the_process_adapter_marks_the_run_truncated(
    tmp_path: Path,
) -> None:
    """The adapter caps what it captures (memory), the artifact writer caps
    what it keeps (disk); either bound tripping makes the record say so."""
    from dataclasses import replace

    process = FakeProcess(stdout="head")
    process.result = replace(process.result, output_truncated=True)
    h = FullHarness(tmp_path, chores={"tidy": COMMAND}, process=process)
    r = run_chore("tidy", h.deps().as_run_deps()).record
    assert r and r.status is RunStatus.SUCCEEDED and r.truncated is True
    (request,) = process.requests
    assert request.max_output_bytes == 50 * 1024 * 1024  # max_run_dir_bytes


def test_output_truncated_by_the_agent_marks_the_run(tmp_path: Path) -> None:
    """Output the process runner dropped marks the record truncated on the
    agent path, as it does on the command path."""
    from dataclasses import replace

    agent = FakeAgent()
    agent.result = replace(agent.result, output_truncated=True)
    h = FullHarness(tmp_path, chores={"rev": AGENT}, agent=agent)
    r = run_chore("rev", h.deps().as_run_deps()).record
    assert r and r.status is RunStatus.SUCCEEDED and r.truncated is True
