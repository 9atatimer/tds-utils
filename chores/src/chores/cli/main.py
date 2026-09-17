"""Entry point for the ``chores`` command.

Thin by design (coding skill 1.7): parse arguments, call an application
function, shape the result. The composition root lives in
:mod:`chores.cli.wiring`; tests pass a Deps built from fakes as ``obj``.
"""

from __future__ import annotations

from datetime import timedelta
from typing import cast

import click

from chores import __version__
from chores.adapters.scheduler import SchedulerInstaller
from chores.application import status as queries
from chores.application.deps import Deps
from chores.application.run import run_chore
from chores.application.tick import tick as run_tick
from chores.cli import render
from chores.domain.errors import InfrastructureError
from chores.domain.run import RunStatus

_ARTIFACT_FLAGS = ("transcript", "stdout", "stderr", "errors", "definition")
_ARTIFACT_NAMES = {
    "transcript": "transcript.jsonl",
    "stdout": "stdout.log",
    "stderr": "stderr.log",
    "errors": "errors.log",
    "definition": "definition.md",
}


def _deps(ctx: click.Context) -> Deps:
    """The Deps bundle: injected by tests as ``obj``, else built by the wiring."""
    if not isinstance(ctx.obj, Deps):
        from chores.cli.wiring import build_deps

        try:
            ctx.obj = build_deps()
        except ValueError as e:  # OverlappingRoots: refuse before touching disk
            click.echo(f"chores: {e}", err=True)
            ctx.exit(1)
    deps: Deps = ctx.obj
    return deps


@click.group()
@click.version_option(__version__, prog_name="chores")
@click.pass_context
def main(ctx: click.Context) -> None:
    """Laptop-local herd of LLM-adjacent scheduled jobs."""


@main.command("list")
@click.pass_context
def list_cmd(ctx: click.Context) -> None:
    """List definitions (valid and invalid)."""
    defs = _deps(ctx).definitions.load()
    for c in defs.chores:
        state = "on " if c.enabled else "off"
        click.echo(
            f"{state} {c.name:24} {c.kind.value:8} "
            f"{c.schedule.expression:16} {c.backend or ''}"
        )
    for i in defs.invalid:
        click.echo(f"!!  {i.name:24} INVALID: {i.error}")


@main.command()
@click.pass_context
def validate(ctx: click.Context) -> None:
    """Validate every definition, backend and config; exit 1 on any problem."""
    deps = _deps(ctx)
    view = queries.status(deps)
    problems = [f"{c.name}: {c.invalid}" for c in view.chores if c.invalid] + list(
        view.warnings
    )
    for p in problems:
        click.echo(p)
    if problems:
        ctx.exit(1)
    click.echo(f"ok: {len(view.chores)} chore(s)")


@main.command("status")
@click.option("--json", "as_json", is_flag=True, help="Emit the StatusView as JSON.")
@click.pass_context
def status_cmd(ctx: click.Context, as_json: bool) -> None:
    """What is scheduled, running, spent and broken."""
    view = queries.status(_deps(ctx))
    click.echo(render.status_json(view) if as_json else render.status_text(view))


@main.command("runs")
@click.option("--chore", default=None)
@click.option("--since", "since_hours", type=float, default=None, help="Hours back.")
@click.option(
    "--status",
    "statuses",
    multiple=True,
    type=click.Choice([s.value for s in RunStatus]),
)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def runs_cmd(
    ctx: click.Context,
    chore: str | None,
    since_hours: float | None,
    statuses: tuple[str, ...],
    as_json: bool,
) -> None:
    """Past runs, newest first."""
    records = queries.runs(
        _deps(ctx),
        chore=chore,
        since=timedelta(hours=since_hours) if since_hours else None,
        statuses=[RunStatus(s) for s in statuses],
    )
    click.echo(render.records_json(records) if as_json else render.runs_text(records))


@main.command()
@click.argument("run_id")
@click.option("--json", "as_json", is_flag=True)
@click.option("--transcript", "artifact", flag_value="transcript")
@click.option("--stdout", "artifact", flag_value="stdout")
@click.option("--stderr", "artifact", flag_value="stderr")
@click.option("--errors", "artifact", flag_value="errors")
@click.option("--definition", "artifact", flag_value="definition")
@click.pass_context
def show(ctx: click.Context, run_id: str, as_json: bool, artifact: str | None) -> None:
    """One run: its record, or one of its artifacts."""
    deps = _deps(ctx)
    record = queries.show(deps, run_id)
    if record is None:
        click.echo(f"no run {run_id}")
        ctx.exit(1)
        return
    if artifact:
        click.echo(queries.artifact(deps, run_id, _ARTIFACT_NAMES[artifact]), nl=False)
        return
    if as_json:
        click.echo(render.records_json([record]))
        return
    click.echo(render.runs_text([record]))
    if record.reason:
        click.echo(f"reason: {record.reason}")


@main.command()
@click.argument("name")
@click.option(
    "--force", is_flag=True, help="Lift overlap, battery and offline refusals only."
)
@click.option(
    "--dry-run", is_flag=True, help="Print the resolved plan; execute nothing."
)
@click.pass_context
def run(ctx: click.Context, name: str, force: bool, dry_run: bool) -> None:
    """Run one chore now (admission still applies).

    Exit 0 ran and succeeded, 1 no such chore, 2 ran and failed (or invalid),
    3 refused by admission (paused, ceiling, overlap, offline, battery).
    """
    outcome = run_chore(name, _deps(ctx).as_run_deps(), force=force, dry_run=dry_run)
    if outcome.plan is not None:
        p = outcome.plan
        click.echo(f"chore:     {p.chore} ({p.kind})")
        click.echo(f"backend:   {p.backend or '-'}  model: {p.model or '-'}")
        click.echo(f"cwd:       {p.cwd}")
        click.echo(f"argv:      {' '.join(p.argv) if p.argv else '-'}")
        click.echo(f"budget:    {p.budget}")
        click.echo(f"env:       {', '.join(p.env_names)}")
        click.echo(f"secrets:   {', '.join(p.secret_names) or '-'}")
        click.echo(
            f"admission: {p.admission}"
            + (f": {p.admission_reason}" if p.admission_reason else "")
        )
        return
    click.echo(outcome.message)
    record = outcome.record
    if record is None:
        ctx.exit(1)
    elif record.status.is_failure or record.status in (
        RunStatus.INVALID,
        RunStatus.KILLED,
        RunStatus.OFFLINE,
    ):
        ctx.exit(2)
    elif not record.status.is_run_terminal:
        ctx.exit(3)  # refused: SKIPPED_* or DEFERRED_BATTERY; nothing ran


@main.command()
@click.pass_context
def tick(ctx: click.Context) -> None:
    """One scheduler pass (what launchd or systemd invokes every interval)."""
    report = run_tick(_deps(ctx).as_tick_deps())
    if report.locked_out:
        click.echo("another tick holds the lock")
        return
    parts = []
    if report.fired:
        parts.append("fired " + ", ".join(report.fired))
    if report.missed:
        parts.append(
            "missed " + ", ".join(f"{k}x{v}" for k, v in report.missed.items())
        )
    if report.skipped:
        parts.append(
            "skipped " + ", ".join(f"{k} ({v})" for k, v in report.skipped.items())
        )
    if report.interrupted:
        parts.append("interrupted " + ", ".join(report.interrupted))
    if report.invalid:
        parts.append("invalid " + ", ".join(report.invalid))
    for w in report.warnings:
        click.echo(f"WARNING: {w}")
    click.echo("; ".join(parts) or "nothing due")


@main.command()
@click.argument("reason", required=False, default="")
@click.option("--chore", default=None, help="Pause one chore instead of everything.")
@click.pass_context
def pause(ctx: click.Context, reason: str, chore: str | None) -> None:
    """Stop every new run (or one chore's) until resume."""
    queries.pause(_deps(ctx), reason, chore=chore)
    click.echo(f"paused {chore or 'all chores'}")


@main.command()
@click.argument("chore", required=False, default=None)
@click.pass_context
def resume(ctx: click.Context, chore: str | None) -> None:
    """Clear the global pause, or one chore's breaker pause."""
    queries.resume(_deps(ctx), chore=chore)
    click.echo(f"resumed {chore or 'all chores'}")


@main.command()
@click.argument("run_id")
@click.pass_context
def kill(ctx: click.Context, run_id: str) -> None:
    """Signal a running run's whole process group."""
    click.echo(queries.kill(_deps(ctx), run_id))


@main.command()
@click.argument("text", required=False, default=None)
@click.option("--dismiss", "dismiss_id", default=None, help="Mark a notification read.")
@click.option("--level", default="info", type=click.Choice(["info", "alert"]))
@click.pass_context
def notify(
    ctx: click.Context, text: str | None, dismiss_id: str | None, level: str
) -> None:
    """Post a message to the dashboard (from inside a run or any shell)."""
    deps = _deps(ctx)
    if dismiss_id:
        click.echo(
            "dismissed"
            if queries.dismiss(deps, dismiss_id)
            else f"no notification {dismiss_id}"
        )
        return
    if not text:
        raise click.UsageError("give a message or --dismiss ID")
    env = deps.inherited_env
    names = [n for n in env.get("CHORES_SECRET_NAMES", "").split(",") if n]
    n = queries.notify(
        deps,
        text,
        level=level,
        run_id=env.get("CHORES_RUN_ID"),
        chore=env.get("CHORES_CHORE"),
        secret_names=names,
    )
    if level == "alert":
        deps.notifier.alert(title="chores", text=n.text)
    click.echo(n.id)


@main.command()
@click.pass_context
def prune(ctx: click.Context) -> None:
    """Delete run directories older than retention_days (the ledger stays)."""
    removed = queries.prune(_deps(ctx))
    click.echo(f"pruned {len(removed)} run(s)")


def _installer(ctx: click.Context) -> SchedulerInstaller:
    deps = _deps(ctx)
    installer = deps.installer
    if installer is None:
        click.echo(
            "no scheduler installer for this platform (macOS launchd, Linux systemd)"
        )
        ctx.exit(1)
    return cast(SchedulerInstaller, installer)


@main.command()
@click.option("--dry-run", is_flag=True)
@click.pass_context
def install(ctx: click.Context, dry_run: bool) -> None:
    """Install the tick as a launchd agent (macOS) or systemd user timer (Linux)."""
    deps = _deps(ctx)
    interval = deps.definitions.load().config.tick_interval_sec
    try:
        lines = _installer(ctx).install(interval_sec=interval, dry_run=dry_run)
    except InfrastructureError as e:
        click.echo(f"install failed: {e}", err=True)
        ctx.exit(1)
    for line in lines:
        click.echo(line)


@main.command()
@click.pass_context
def uninstall(ctx: click.Context) -> None:
    """Remove the scheduler agent or timer."""
    for line in _installer(ctx).uninstall():
        click.echo(line)


@main.command()
@click.pass_context
def ui(ctx: click.Context) -> None:
    """The dashboard as a TUI (needs the tui extra: textual)."""
    try:
        from chores.tui.app import run_ui
    except ImportError as e:  # pragma: no cover - depends on the extra
        raise click.ClickException(
            "the TUI needs textual: `uv sync --all-extras` or `pip install chores[tui]`"
        ) from e
    run_ui(_deps(ctx))
