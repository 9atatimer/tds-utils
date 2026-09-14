"""ChoresApp -- a Textual TUI over ``status()`` (Subsystem 6).

One periodic refresh of the StatusView; every verb calls the same
application function the CLI calls. ``r`` launches the selected chore
detached (like tick does), so the dashboard never blocks on a run.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Footer, Header, Static

from chores.application import status as queries
from chores.application.deps import Deps
from chores.application.status import StatusView
from chores.cli import render

REFRESH_SEC = 5.0
_COLUMNS = ("chore", "state", "schedule", "next", "last run", "usage", "last failure")


class ChoresApp(App[None]):
    TITLE = "chores"
    BINDINGS = [
        Binding("r", "run_now", "run now"),
        Binding("p", "toggle_pause", "pause/resume all"),
        Binding("d", "dismiss", "dismiss notification"),
        Binding("enter", "open_run", "open last run"),
        Binding("g", "refresh", "refresh"),
        Binding("q", "quit", "quit"),
    ]

    def __init__(self, deps: Deps, *, refresh_sec: float = REFRESH_SEC) -> None:
        super().__init__()
        self._deps = deps
        self._refresh_sec = refresh_sec
        self.view: StatusView | None = None
        self.message = ""

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield Static("", id="banner")
            yield DataTable(id="chores", cursor_type="row")
            yield Static("", id="usage")
            yield Static("", id="notifications")
            yield Static("", id="detail")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#chores", DataTable)
        table.add_columns(*_COLUMNS)
        self.action_refresh()
        self.set_interval(self._refresh_sec, self.action_refresh)

    # --- rendering -----------------------------------------------------------

    def action_refresh(self) -> None:
        view = queries.status(self._deps)
        self.view = view
        table = self.query_one("#chores", DataTable)
        selected = table.cursor_row
        table.clear()
        for chore in view.chores:
            table.add_row(*render._chore_row(chore), key=chore.name)
        if 0 <= selected < table.row_count:
            table.move_cursor(row=selected)
        banner = []
        if view.paused:
            banner.append(f"PAUSED: {view.paused}")
        sched = view.scheduler
        tick = render._when(sched.last_tick)
        installed = {True: "installed", False: "NOT INSTALLED", None: "?"}[
            sched.installed
        ]
        banner.append(
            f"scheduler {installed}, last tick {tick}{' STALE' if sched.stale else ''}"
        )
        if self.message:
            banner.append(self.message)
        self.query_one("#banner", Static).update("  |  ".join(banner))
        usage = "; ".join(
            f"{u.scope}: {u.usage.tokens}t"
            + (f" ${u.usage.usd:.3f}" if u.usage.usd is not None else "")
            for u in view.usage
        )
        self.query_one("#usage", Static).update(f"24h: {usage}")
        notes = "\n".join(f"[{n.id}] {n.level} {n.text}" for n in view.notifications)
        self.query_one("#notifications", Static).update(notes or "no notifications")

    def _selected_chore(self) -> str | None:
        table = self.query_one("#chores", DataTable)
        if self.view is None or table.row_count == 0:
            return None
        return str(table.get_row_at(table.cursor_row)[0])

    # --- verbs ---------------------------------------------------------------

    def action_run_now(self) -> None:
        name = self._selected_chore()
        if name is None:
            return
        self._deps.launch(name)
        self.message = f"launched {name}"
        self.action_refresh()

    def action_toggle_pause(self) -> None:
        if self._deps.store.paused() is None:
            queries.pause(self._deps, "paused from the dashboard")
        else:
            queries.resume(self._deps)
        self.action_refresh()

    def action_dismiss(self) -> None:
        if self.view and self.view.notifications:
            queries.dismiss(self._deps, self.view.notifications[0].id)
        self.action_refresh()

    def on_data_table_row_selected(self, _event: DataTable.RowSelected) -> None:
        self.action_open_run()

    def action_open_run(self) -> None:
        name = self._selected_chore()
        if name is None or self.view is None:
            return
        chore = next(c for c in self.view.chores if c.name == name)
        summary = chore.last_run
        if summary is None:
            self.query_one("#detail", Static).update(f"{name}: no runs yet")
            return
        transcript = queries.artifact(self._deps, summary.run_id, "transcript.jsonl")
        stdout = queries.artifact(self._deps, summary.run_id, "stdout.log")
        errors = queries.artifact(self._deps, summary.run_id, "errors.log")
        body = transcript or stdout or errors or "(no artifacts)"
        headline = f"{summary.run_id} {summary.status.value} {summary.reason or ''}"
        self.query_one("#detail", Static).update(f"{headline}\n{body[-2000:]}")


def run_ui(deps: Deps) -> None:
    ChoresApp(deps).run()
