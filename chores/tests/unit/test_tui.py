"""The Textual dashboard, driven by its pilot against fakes (Subsystem 6)."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import DataTable, Static

from chores.cli.main import main
from chores.tui.app import ChoresApp

from ._harness import FullHarness
from .test_runner import COMMAND, PROMPT

pytestmark = pytest.mark.asyncio


async def test_dashboard_lists_chores_and_refreshes(tmp_path: Path) -> None:
    h = FullHarness(
        tmp_path, chores={"brand": PROMPT, "tidy": COMMAND}, installed=False
    )
    app = ChoresApp(h.deps(), refresh_sec=60)
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one("#chores", DataTable)
        assert table.row_count == 2
        assert "NOT INSTALLED" in str(app.query_one("#banner", Static).render())
        assert "no notifications" in str(
            app.query_one("#notifications", Static).render()
        )


async def test_run_now_launches_the_selected_chore_detached(tmp_path: Path) -> None:
    h = FullHarness(tmp_path, chores={"brand": PROMPT, "tidy": COMMAND})
    app = ChoresApp(h.deps(), refresh_sec=60)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("down")
        await pilot.press("r")
        await pilot.pause()
        assert h.launched == ["tidy"]
        assert "launched tidy" in str(app.query_one("#banner", Static).render())


async def test_pause_toggles_the_global_sentry(tmp_path: Path) -> None:
    h = FullHarness(tmp_path, chores={"tidy": COMMAND})
    app = ChoresApp(h.deps(), refresh_sec=60)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        assert h.store.paused() == "paused from the dashboard"
        assert "PAUSED" in str(app.query_one("#banner", Static).render())
        await pilot.press("p")
        await pilot.pause()
        assert h.store.paused() is None


async def test_dismiss_and_open_run(tmp_path: Path) -> None:
    from click.testing import CliRunner

    h = FullHarness(tmp_path, chores={"tidy": COMMAND})
    CliRunner().invoke(main, ["run", "tidy"], obj=h.deps(), catch_exceptions=False)
    h.store.notify(at=h.clock.now_utc(), level="info", text="hello there")
    app = ChoresApp(h.deps(), refresh_sec=60)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "hello there" in str(app.query_one("#notifications", Static).render())
        await pilot.press("d")
        await pilot.pause()
        assert h.store.notifications() == []
        await pilot.press("enter")
        await pilot.pause()
        assert "SUCCEEDED" in str(app.query_one("#detail", Static).render())


async def test_status_warnings_show_in_the_banner(tmp_path: Path) -> None:
    h = FullHarness(tmp_path, chores={"tidy": COMMAND}, installed=True)
    (tmp_path / "home" / "backends.yaml").write_text(
        "backends:\n  unused:\n    type: ollama\n    model: m\n"
        "    ceiling: {usd: 1.0}\n"
    )
    app = ChoresApp(h.deps(), refresh_sec=60)
    async with app.run_test() as pilot:
        await pilot.pause()
        banner = str(app.query_one("#banner", Static).render())
        assert "WARNING" in banner and "usd ceiling" in banner
