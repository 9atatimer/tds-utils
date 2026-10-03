"""Entry point for the ``chores`` command.

Thin by design (coding skill 1.7): parse arguments, call an application
function, shape the result. The composition root lives in
:mod:`chores.cli.wiring`; tests pass a Deps built from fakes as ``obj``.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import cast

import click

from chores import __version__
from chores.adapters.scheduler import SchedulerInstaller
from chores.application import status as queries
from chores.application.arm import arm_chore, cancel_armed
from chores.application.deps import Deps
from chores.application.run import run_chore
from chores.application.tick import tick as run_tick
from chores.cli import render
from chores.cli.wiring import forget_home, remember_home, restore_home
from chores.domain.errors import InfrastructureError
from chores.domain.run import RunStatus
from chores.ports.host import ClockPort

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
    # definitions, backends and bindings only: a shrunk ledger or a stale
    # installed interval is a status warning, not an invalid tree
    problems = [f"{c.name}: {c.invalid}" for c in view.chores if c.invalid] + list(
        view.problems
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
    deps = _deps(ctx)
    view = queries.status(deps)
    click.echo(
        render.status_json(view)
        if as_json
        else render.status_text(view, local=deps.clock.local_from_utc)
    )


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
    deps = _deps(ctx)
    records = queries.runs(
        deps,
        chore=chore,
        since=timedelta(hours=since_hours) if since_hours is not None else None,
        statuses=[RunStatus(s) for s in statuses],
    )
    click.echo(
        render.records_json(records)
        if as_json
        else render.runs_text(records, local=deps.clock.local_from_utc)
    )


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
    click.echo(render.runs_text([record], local=deps.clock.local_from_utc))
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
@click.option(
    "--at",
    "at",
    default=None,
    metavar="WHEN",
    help="Arm instead of running now: 'now', 'HH:MM' (next occurrence, local) "
    "or 'YYYY-MM-DDTHH:MM' (local). The tick starts it at that time.",
)
@click.option("--armed", "armed_run_id", default=None, hidden=True)
@click.pass_context
def run(
    ctx: click.Context,
    name: str,
    force: bool,
    dry_run: bool,
    at: str | None,
    armed_run_id: str | None,
) -> None:
    """Run one chore now, or arm it for later with --at (admission applies).

    Exit 0 ran and succeeded (or armed), 1 no such chore or refused arming,
    2 ran and failed (or invalid), 3 refused by admission (paused, ceiling,
    overlap, offline, battery).
    """
    deps = _deps(ctx)
    if at is not None:
        if force or dry_run:
            raise click.UsageError("--at cannot be combined with --force or --dry-run")
        try:
            start_at = parse_at(at, deps.clock)
        except ValueError as e:
            raise click.UsageError(f"--at: {e}") from e
        armed = arm_chore(name, start_at, deps.as_run_deps(), armed_by="cli")
        click.echo(armed.message)
        if armed.run_id is None:
            ctx.exit(1)
        return
    outcome = run_chore(
        name,
        deps.as_run_deps(),
        force=force,
        dry_run=dry_run,
        armed_run_id=armed_run_id,
    )
    if outcome.plan is not None:
        p = outcome.plan
        click.echo(f"chore:     {p.chore} ({p.kind}, port {p.port or '-'})")
        click.echo(f"backend:   {p.backend or '-'}  model: {p.model or '-'}")
        click.echo(f"cwd:       {p.cwd}")
        click.echo(f"argv:      {' '.join(p.argv) if p.argv else '-'}")
        click.echo(f"budget:    {p.budget}")
        for scope, ceiling in p.ceilings.items():
            click.echo(f"ceiling:   {scope}: {ceiling}")
        if not p.ceilings:
            click.echo("ceiling:   none applies")
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
@click.argument("run_id")
@click.pass_context
def cancel(ctx: click.Context, run_id: str) -> None:
    """Cancel an armed run before it starts (`chores kill` stops a running one)."""
    if cancel_armed(run_id, _deps(ctx)):
        click.echo(f"{run_id}: cancelled")
        return
    click.echo(f"{run_id}: not armed; nothing cancelled")
    ctx.exit(1)


def parse_at(text: str, clock: ClockPort) -> datetime:
    """``now``, ``HH:MM`` (the next occurrence, local) or an ISO 8601 local
    date-time, as a naive UTC instant. Raises ValueError."""
    now_utc = clock.now_utc()
    if text.strip() == "now":
        return now_utc
    now_local = clock.now_local()
    offset = now_local - now_utc  # this machine's local - UTC, right now
    if re.fullmatch(r"\d{1,2}:\d{2}", text.strip()):
        hours, minutes = (int(v) for v in text.strip().split(":"))
        if hours > 23 or minutes > 59:
            raise ValueError(f"{text!r} is not a time of day")
        local = now_local.replace(hour=hours, minute=minutes, second=0, microsecond=0)
        if local < now_local.replace(second=0, microsecond=0):
            local += timedelta(days=1)
        return local - offset
    try:
        local = datetime.fromisoformat(text.strip())
    except ValueError as e:
        raise ValueError(f"{text!r}: expected now, HH:MM or YYYY-MM-DDTHH:MM") from e
    if local.tzinfo is not None:
        raise ValueError("give a local time without a zone")
    return local - offset


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
    click.echo(n.id)  # post() already raised the desktop alert for level=alert


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


def _unit_env(deps: Deps) -> dict[str, str]:
    """What the tick unit must carry to see the same herd `install` saw: the
    definitions root always, and the XDG roots when this shell set them."""
    env = {"CHORES_HOME": deps.paths.chores_home}
    for key in ("XDG_STATE_HOME", "XDG_DATA_HOME"):
        value = deps.inherited_env.get(key)
        if value:
            env[key] = value
    return env


@main.command()
@click.option("--dry-run", is_flag=True)
@click.pass_context
def install(ctx: click.Context, dry_run: bool) -> None:
    """Install the tick as a launchd agent (macOS) or systemd user timer (Linux)."""
    deps = _deps(ctx)
    defs = deps.definitions.load()
    if defs.config_error is not None:
        click.echo(f"install refused: {defs.config_error}", err=True)
        ctx.exit(1)
    interval = defs.config.tick_interval_sec
    installer = _installer(ctx)
    previous: str | None = None
    try:
        # The pointer first: it is the step that can refuse (a symlinked
        # state dir), and refusing before the OS job exists leaves nothing
        # half-installed. If the scheduler then fails, the pointer goes back
        # to what it was: the prior install's, or none.
        if not dry_run:
            previous = remember_home(deps.paths)
        try:
            lines = installer.install(
                interval_sec=interval, dry_run=dry_run, env=_unit_env(deps)
            )
        except InfrastructureError:
            if not dry_run:
                restore_home(deps.paths, previous)
            raise
    except InfrastructureError as e:
        click.echo(f"install failed: {e}", err=True)
        ctx.exit(1)
    if not dry_run:
        lines.append(f"remembered CHORES_HOME={deps.paths.chores_home}")
    for line in lines:
        click.echo(line)


@main.command()
@click.pass_context
def uninstall(ctx: click.Context) -> None:
    """Remove the scheduler agent or timer."""
    try:
        lines = _installer(ctx).uninstall()
    except InfrastructureError as e:
        click.echo(f"uninstall failed: {e}", err=True)
        ctx.exit(1)
    for line in lines:
        click.echo(line)
    forget_home(_deps(ctx).paths)


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
