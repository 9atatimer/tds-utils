"""The status query and the kill control (CHORES.DESIGN.md Subsystem 6):
what every surface renders, asserted on the application function rather than
through a surface.
"""

from __future__ import annotations

from pathlib import Path

from chores.application.run import run_chore
from chores.application.status import status
from chores.domain.kinds import Kind
from chores.domain.run import RunRecord, RunStatus
from chores.ports.store import TickMark

from ._fakes import FakeProcess
from ._harness import COMMAND, T0, FullHarness


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


def test_only_metered_backends_warn_about_an_unpriced_usd_ceiling(
    tmp_path: Path,
) -> None:
    """A free (ollama) or self-reporting (claude-cli) backend needs no price
    table to carry a usd ceiling; a metered one does."""
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
