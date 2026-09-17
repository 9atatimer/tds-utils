"""The status query and the small control use cases (CHORES.DESIGN.md
Subsystem 6): one ``StatusView`` that every surface renders, plus runs /
show / pause / resume / kill / notify / prune."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from chores.application.context import (
    binding_errors,
    ledger_window,
    live_running,
    load_context,
    post,
)
from chores.application.deps import Deps
from chores.domain.budget import Ceiling, Usage
from chores.domain.policies import redact
from chores.domain.run import Billing, RunRecord, RunStatus
from chores.ports.store import Notification

STALE_AFTER_TICKS = 3


@dataclass(frozen=True, slots=True)
class RunSummary:
    run_id: str
    status: RunStatus
    started: datetime
    ended: datetime | None
    reason: str | None
    usage: Usage | None

    @classmethod
    def of(cls, r: RunRecord) -> RunSummary:
        return cls(r.run_id, r.status, r.started, r.ended, r.reason, r.usage)


@dataclass(frozen=True, slots=True)
class ChoreStatus:
    name: str
    kind: str
    enabled: bool
    paused_by: str | None
    schedule: str
    next_due: datetime | None
    backend: str | None
    invalid: str | None
    running: RunSummary | None
    last_run: RunSummary | None
    last_success: RunSummary | None
    last_failure: RunSummary | None


@dataclass(frozen=True, slots=True)
class ScopeUsage:
    scope: str
    usage: Usage
    ceiling: Ceiling


@dataclass(frozen=True, slots=True)
class SchedulerStatus:
    last_tick: datetime | None
    stale: bool
    installed: bool | None
    tick_interval_sec: int
    ledger_rows: int


@dataclass(frozen=True, slots=True)
class StatusView:
    at: datetime
    paused: str | None
    chores: Sequence[ChoreStatus]
    usage: Sequence[ScopeUsage]
    scheduler: SchedulerStatus
    notifications: Sequence[Notification]
    warnings: Sequence[str] = field(default_factory=tuple)
    """Runtime and operator warnings (ledger shrank, interval drift): shown on
    every surface, never a reason for `chores validate` to fail."""
    problems: Sequence[str] = field(default_factory=tuple)
    """Definition, backend and config problems: what `chores validate` exits
    1 on (also rendered with the warnings)."""

    @property
    def needs_attention(self) -> bool:
        """The menu-bar rule: a failed last run, a breaker pause, or a stale tick."""
        return (
            self.scheduler.stale
            or any(c.paused_by for c in self.chores)
            or any(c.last_run and c.last_run.status.is_failure for c in self.chores)
        )


# --- helpers -----------------------------------------------------------------


def _summaries(
    records: Sequence[RunRecord],
) -> tuple[RunSummary | None, RunSummary | None, RunSummary | None]:
    last_run = last_success = last_failure = None
    for r in records:
        if not r.status.is_run_terminal:
            continue
        if last_run is None:
            last_run = RunSummary.of(r)
        if last_success is None and r.status is RunStatus.SUCCEEDED:
            last_success = RunSummary.of(r)
        if last_failure is None and r.status.is_failure:
            last_failure = RunSummary.of(r)
        if last_run and last_success and last_failure:
            break
    return last_run, last_success, last_failure


def _sum(rows: Sequence[object]) -> Usage:
    total = Usage(0, 0, 0.0)
    for row in rows:
        usage = getattr(row, "usage", None)
        if isinstance(usage, Usage):
            total = total + usage
    return total


# --- the query ---------------------------------------------------------------


def status(deps: Deps) -> StatusView:
    ctx = load_context(deps.definitions, deps.catalog_for)
    now_utc = deps.clock.now_utc()
    now_local = deps.clock.now_local()
    config = ctx.definitions.config
    chores: list[ChoreStatus] = []
    for chore in ctx.definitions.chores:
        records = deps.store.records(chore=chore.name)
        running = live_running(
            deps.store,
            deps.process,
            chore.name,
            now_utc=now_utc,
            pending_grace=timedelta(seconds=config.tick_interval_sec),
        )
        last_run, last_success, last_failure = _summaries(records)
        bindings = binding_errors(ctx, chore, forbidden=deps.paths.forbidden_for_cwd())
        chores.append(
            ChoreStatus(
                name=chore.name,
                kind=chore.kind.value,
                enabled=chore.enabled,
                paused_by=deps.store.chore_paused(chore.name),
                schedule=chore.schedule.expression,
                next_due=chore.schedule.next_after(now_local)
                if chore.enabled
                else None,
                backend=chore.backend,
                invalid="; ".join(bindings) or None,
                running=RunSummary.of(running) if running else None,
                last_run=last_run,
                last_success=last_success,
                last_failure=last_failure,
            )
        )
    for invalid in ctx.definitions.invalid:
        chores.append(
            ChoreStatus(
                name=invalid.name,
                kind="?",
                enabled=False,
                paused_by=None,
                schedule="?",
                next_due=None,
                backend=None,
                invalid=invalid.error,
                running=None,
                last_run=None,
                last_success=None,
                last_failure=None,
            )
        )
    window = ledger_window(deps.store, now_utc=now_utc)
    usage: list[ScopeUsage] = [ScopeUsage("global", _sum(window), config.ceiling)]
    for name, backend in ctx.definitions.backends.items():
        rows = [r for r in window if r.backend == name]
        usage.append(ScopeUsage(f"backend:{name}", _sum(rows), backend.ceiling))
    subscription = _sum([r for r in window if r.billing is Billing.SUBSCRIPTION])
    if subscription.tokens:
        usage.append(ScopeUsage("subscription", subscription, Ceiling()))
    mark = deps.store.last_tick()
    stale = mark is None or (
        now_utc - mark.at
        > timedelta(seconds=config.tick_interval_sec * STALE_AFTER_TICKS)
    )
    scheduler = SchedulerStatus(
        last_tick=mark.at if mark else None,
        stale=stale,
        installed=deps.scheduler_installed(),
        tick_interval_sec=config.tick_interval_sec,
        ledger_rows=deps.store.ledger_count(),
    )
    problems = [*ctx.definitions.errors, *ctx.catalog.errors]
    for name in ctx.definitions.backends:
        spec = ctx.catalog.spec(name)  # None: refused, already in catalog.errors
        if (
            spec is not None
            and spec.ceiling.usd is not None
            and not spec.priced
            and spec.billing in (None, Billing.METERED)
        ):
            problems.append(f"backend {name!r} has a usd ceiling but no price table")
    warnings: list[str] = []
    if mark is not None and scheduler.ledger_rows < mark.ledger_rows:
        warnings.append(
            f"ledger shrank from {mark.ledger_rows} rows to {scheduler.ledger_rows} "
            "since the last tick"
        )
    installed_interval = _installed_interval(deps)
    if (
        installed_interval is not None
        and installed_interval != config.tick_interval_sec
    ):
        warnings.append(
            f"installed tick interval {installed_interval}s differs from config "
            f"{config.tick_interval_sec}s; run `chores install` again"
        )
    return StatusView(
        at=now_utc,
        paused=deps.store.paused(),
        chores=chores,
        usage=usage,
        scheduler=scheduler,
        notifications=deps.store.notifications(),
        warnings=[*problems, *warnings],
        problems=problems,
    )


def _installed_interval(deps: Deps) -> int | None:
    probe = getattr(deps.installer, "installed_interval", None)
    if probe is None:
        return None
    value = probe()
    return int(value) if isinstance(value, int) else None


# --- runs and show -----------------------------------------------------------


def runs(
    deps: Deps,
    *,
    chore: str | None = None,
    since: timedelta | None = None,
    statuses: Sequence[RunStatus] | None = None,
) -> Sequence[RunRecord]:
    since_at = deps.clock.now_utc() - since if since is not None else None
    found = deps.store.records(chore=chore, since=since_at)
    if statuses:
        wanted = set(statuses)
        found = [r for r in found if r.status in wanted]
    return found


def show(deps: Deps, run_id: str) -> RunRecord | None:
    return deps.store.read_record(run_id)


def artifact(deps: Deps, run_id: str, name: str) -> str:
    return deps.store.read_artifact(run_id, name)


# --- controls ----------------------------------------------------------------


def pause(deps: Deps, reason: str, *, chore: str | None = None) -> None:
    if chore is None:
        deps.store.pause(reason or "(no reason recorded)")
    else:
        deps.store.pause_chore(chore, reason or "paused by hand")


def resume(deps: Deps, *, chore: str | None = None) -> None:
    if chore is None:
        deps.store.unpause()
    else:
        deps.store.resume_chore(chore)


def kill(deps: Deps, run_id: str) -> str:
    record = deps.store.read_record(run_id)
    if record is None:
        return f"no run {run_id}"
    if record.status is not RunStatus.RUNNING or record.pgid is None:
        return f"{run_id} is {record.status.value}, nothing to kill"
    if record.pid is None or not deps.process.alive(
        record.pid, process_start=record.process_start or 0.0
    ):
        # The recorded pid is gone (the tick will close it as INTERRUPTED);
        # its group id may already belong to someone else, so never signal it.
        return f"process {record.pid} already gone; nothing signalled"
    deps.store.request_kill(run_id)
    signalled = deps.process.signal_group(record.pgid)
    return (
        f"signalled group {record.pgid}"
        if signalled
        else f"group {record.pgid} already gone"
    )


def notify(
    deps: Deps,
    text: str,
    *,
    level: str = "info",
    run_id: str | None = None,
    chore: str | None = None,
    secret_names: Sequence[str] = (),
) -> Notification:
    values = [deps.inherited_env.get(name, "") for name in secret_names]
    clean = redact(text, values)
    return deps.store.notify(
        at=deps.clock.now_utc(), level=level, text=clean, run_id=run_id, chore=chore
    )


def dismiss(deps: Deps, notification_id: str) -> bool:
    return deps.store.dismiss(notification_id)


def alert(deps: Deps, text: str) -> None:
    post(deps.store, deps.notifier, at=deps.clock.now_utc(), level="alert", text=text)


def prune(deps: Deps) -> list[str]:
    """Delete run directories older than ``retention_days``; returns their ids."""
    ctx = load_context(deps.definitions, deps.catalog_for)
    cutoff = deps.clock.now_utc() - timedelta(
        days=ctx.definitions.config.retention_days
    )
    removed: list[str] = []
    for record in deps.store.records():
        if record.status.is_terminal and record.started < cutoff:
            if deps.store.delete_run(record.run_id):
                removed.append(record.run_id)
    return removed
