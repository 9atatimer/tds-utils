"""The CLI surface (CHORES.DESIGN.md Subsystem 6) through Click's CliRunner."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from click.testing import CliRunner

from chores.cli.main import main
from chores.domain.kinds import Kind
from chores.domain.run import RunRecord, RunStatus
from chores.ports.store import TickMark

from ._fakes import FakeProcess
from ._harness import T0, FullHarness
from .test_runner import AGENT, COMMAND, PROMPT, SECRET

BAD = "---\nname: bad\nkind: prompt\n---\n"


def invoke(h: FullHarness, *args: str) -> tuple[int, str]:
    result = CliRunner().invoke(main, list(args), obj=h.deps(), catch_exceptions=False)
    return result.exit_code, result.output


def test_list_shows_valid_and_invalid(tmp_path: Path) -> None:
    h = FullHarness(tmp_path, chores={"brand": PROMPT, "tidy": COMMAND, "bad": BAD})
    code, out = invoke(h, "list")
    assert code == 0 and "on  brand" in out and "tidy" in out and "INVALID" in out


def test_validate_exit_codes(tmp_path: Path) -> None:
    ok = FullHarness(tmp_path / "a", chores={"tidy": COMMAND})
    assert invoke(ok, "validate")[0] == 0
    bad = FullHarness(tmp_path / "b", chores={"bad": BAD})
    code, out = invoke(bad, "validate")
    assert code == 1 and "bad: " in out


def test_status_text_and_json_agree(tmp_path: Path) -> None:
    h = FullHarness(tmp_path, chores={"brand": PROMPT, "tidy": COMMAND}, installed=True)
    h.store.mark_tick(TickMark(at=h.clock.now_utc(), ledger_rows=0))
    invoke(h, "run", "tidy")
    code, text = invoke(h, "status")
    assert code == 0 and "scheduler: installed" in text and "SUCCEEDED" in text
    assert "brand" in text and "tidy" in text and "24h usage" in text
    code, raw = invoke(h, "status", "--json")
    view = json.loads(raw)
    names = {c["name"]: c for c in view["chores"]}
    assert names["tidy"]["last_run"]["status"] == "SUCCEEDED"
    assert view["needs_attention"] is False and view["scheduler"]["installed"] is True


def test_status_flags_stale_scheduler_and_failures(tmp_path: Path) -> None:
    h = FullHarness(
        tmp_path, chores={"tidy": COMMAND}, process=FakeProcess(exit_code=1)
    )
    invoke(h, "run", "tidy")
    view = json.loads(invoke(h, "status", "--json")[1])
    assert view["scheduler"]["stale"] is True and view["needs_attention"] is True
    assert view["chores"][0]["last_failure"]["status"] == "FAILED"
    assert "STALE" in invoke(h, "status")[1]


def test_runs_filters_and_show_artifacts(tmp_path: Path) -> None:
    h = FullHarness(tmp_path, chores={"brand": PROMPT, "tidy": COMMAND})
    invoke(h, "run", "brand")
    h.clock.advance(60)
    invoke(h, "run", "tidy")
    code, out = invoke(h, "runs")
    assert code == 0 and out.index("tidy-") < out.index("brand-")
    code, out = invoke(h, "runs", "--chore", "brand", "--json")
    rows = json.loads(out)
    assert [r["chore"] for r in rows] == ["brand"]
    run_id = rows[0]["run_id"]
    assert '"role": "user"' in invoke(h, "show", run_id, "--transcript")[1]
    assert invoke(h, "show", run_id, "--definition")[1].startswith("---\nname: brand")
    assert (
        json.loads(invoke(h, "show", run_id, "--json")[1])[0]["status"] == "SUCCEEDED"
    )
    assert invoke(h, "show", "nope")[0] == 1
    assert (
        invoke(h, "runs", "--status", "FAILED")[1].count("\n") == 2
    )  # header + rule only


def test_run_exit_codes_and_dry_run(tmp_path: Path) -> None:
    h = FullHarness(tmp_path, chores={"brand": PROMPT, "tidy": COMMAND, "bad": BAD})
    assert invoke(h, "run", "tidy")[0] == 0
    assert invoke(h, "run", "nope")[0] == 1
    assert invoke(h, "run", "bad")[0] == 2
    code, out = invoke(h, "run", "brand", "--dry-run")
    assert (
        code == 0 and "backend:   gw" in out and "API_KEY" in out and SECRET not in out
    )
    assert "admission: ADMIT" in out and h.store.records(chore="brand") == []
    failing = FullHarness(
        tmp_path / "f", chores={"tidy": COMMAND}, process=FakeProcess(exit_code=3)
    )
    assert invoke(failing, "run", "tidy")[0] == 2


def test_tick_reports_what_it_did(tmp_path: Path) -> None:
    hourly = COMMAND.replace("'* * * * *'", "'0 * * * *'")
    h = FullHarness(tmp_path, chores={"tidy": hourly})
    h.store.mark_tick(
        TickMark(
            at=h.clock.now_utc() - timedelta(seconds=60),
            ledger_rows=0,
        )
    )
    code, out = invoke(h, "tick")
    assert code == 0 and "fired tidy" in out and h.launched == ["tidy"]
    h.store.lock_held = True
    assert "lock" in invoke(h, "tick")[1]


def test_pause_resume_global_and_chore(tmp_path: Path) -> None:
    h = FullHarness(tmp_path, chores={"tidy": COMMAND})
    invoke(h, "pause", "flight mode")
    assert h.store.paused() == "flight mode"
    assert "SKIPPED_PAUSED" in invoke(h, "run", "tidy")[1]
    invoke(h, "resume")
    assert h.store.paused() is None
    invoke(h, "pause", "--chore", "tidy", "hands off")
    assert h.store.chore_paused("tidy") == "hands off"
    invoke(h, "resume", "tidy")
    assert h.store.chore_paused("tidy") is None


def test_kill_signals_the_group_of_a_running_run(tmp_path: Path) -> None:
    h = FullHarness(tmp_path, chores={"tidy": COMMAND})
    live = RunRecord.pending(
        run_id="tidy-x", chore="tidy", kind=Kind.COMMAND, definition_rev="r", started=T0
    ).start(pid=55, pgid=55, process_start=1.0)
    h.store.write_record(live)
    code, out = invoke(h, "kill", "tidy-x")
    assert "signalled group 55" in out and h.process.signalled == [55]
    assert h.store.kill_requested("tidy-x")
    assert "nothing to kill" in invoke(h, "kill", "tidy-x")[1] or "signalled" in out
    assert invoke(h, "kill", "nope")[1].startswith("no run")


def test_notify_from_inside_a_run_redacts_named_secrets(tmp_path: Path) -> None:
    env = {
        "PATH": "/usr/bin",
        "HOME": "/h",
        "CHORES_RUN_ID": "tidy-x",
        "CHORES_CHORE": "tidy",
        "CHORES_SECRET_NAMES": "API_KEY",
        "API_KEY": "hunter2",
    }
    h = FullHarness(tmp_path, chores={"tidy": COMMAND}, env=env)
    code, out = invoke(h, "notify", "key is hunter2 done")
    n = h.store.notifications()[0]
    assert code == 0 and out.strip() == n.id
    assert (
        n.text == "key is [REDACTED] done"
        and n.run_id == "tidy-x"
        and n.chore == "tidy"
    )
    assert invoke(h, "notify", "--dismiss", n.id)[1].strip() == "dismissed"
    assert h.store.notifications() == []
    invoke(h, "notify", "--level", "alert", "boom")
    assert h.notifier.alerts == [("chores", "boom")]
    assert invoke(h, "notify")[0] != 0


def test_prune_removes_old_terminal_runs_but_keeps_the_ledger(tmp_path: Path) -> None:
    h = FullHarness(tmp_path, chores={"tidy": COMMAND}, config="retention_days: 1\n")
    invoke(h, "run", "tidy")
    h.clock.advance(3 * 86400)
    invoke(h, "run", "tidy")
    code, out = invoke(h, "prune")
    assert code == 0 and "pruned 1 run(s)" in out
    assert len(h.store.records()) == 1 and h.store.ledger_count() == 2


def test_agent_run_through_cli(tmp_path: Path) -> None:
    h = FullHarness(tmp_path, chores={"rev": AGENT})
    code, out = invoke(h, "run", "rev")
    assert code == 0 and "SUCCEEDED" in out
    assert h.store.records()[0].status is RunStatus.SUCCEEDED


def test_install_and_uninstall_go_through_the_installer(tmp_path: Path) -> None:
    from dataclasses import replace

    from chores.adapters.scheduler import LaunchdInstaller

    calls: list[list[str]] = []
    inst = LaunchdInstaller(
        home=tmp_path / "h", uid=7, run=lambda argv: calls.append(argv) or 0
    )
    h = FullHarness(
        tmp_path, chores={"tidy": COMMAND}, config="tick_interval_sec: 30\n"
    )
    deps = replace(h.deps(), installer=inst, scheduler_installed=inst.installed)
    r = CliRunner().invoke(
        main, ["install", "--dry-run"], obj=deps, catch_exceptions=False
    )
    assert "would write" in r.output and calls == []
    r = CliRunner().invoke(main, ["install"], obj=deps, catch_exceptions=False)
    assert "every 30s" in r.output and inst.installed()
    view = json.loads(CliRunner().invoke(main, ["status", "--json"], obj=deps).output)
    assert view["scheduler"]["installed"] is True and view["warnings"] == []
    deps2 = replace(deps, definitions=h.definitions)
    (tmp_path / "home" / "config.yaml").write_text("tick_interval_sec: 60\n")
    view = json.loads(CliRunner().invoke(main, ["status", "--json"], obj=deps2).output)
    assert any("differs" in w for w in view["warnings"])
    r = CliRunner().invoke(main, ["uninstall"], obj=deps, catch_exceptions=False)
    assert "booted out" in r.output and not inst.installed()


def test_validate_reports_binding_violations(tmp_path: Path) -> None:
    """Given a chore whose backend does not exist, Then validate exits 1 naming it."""
    orphan = PROMPT.replace("backend: gw", "backend: nowhere")
    h = FullHarness(tmp_path, chores={"brand": orphan})
    code, out = invoke(h, "validate")
    assert code == 1 and "brand: backend 'nowhere' is not configured" in out
    code, out = invoke(h, "run", "brand", "--dry-run")
    assert code == 1 and "invalid" in out and h.store.records() == []
