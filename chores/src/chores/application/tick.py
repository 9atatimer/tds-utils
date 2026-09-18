"""The tick use case (CHORES.DESIGN.md Subsystem 2): exclusion, liveness,
interrupted detection, due and missed detection, admission, spawn.
Stateless: everything it knows comes from the store and the clock.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from chores.application.context import (
    Artifacts,
    Context,
    Host,
    admit,
    apply_breaker,
    binding_errors,
    ensure_ledgered,
    invalid_record_name,
    load_context,
    mint_run_id,
    post,
    write_outcome,
)
from chores.application.paths import Paths
from chores.domain.chore import Chore
from chores.domain.errors import ChoresError, DomainError, InfrastructureError
from chores.domain.kinds import Kind
from chores.domain.policies import Decision
from chores.domain.run import RunRecord, RunStatus, to_ledger_row
from chores.domain.schedule import due_policy
from chores.ports.backends import BackendCatalogPort
from chores.ports.definitions import Definitions, DefinitionsPort
from chores.ports.host import ClockPort, NetworkPort, NotifierPort, PowerPort
from chores.ports.process import ProcessPort
from chores.ports.store import RunStorePort, TickMark

# Statuses that consume a slot: the window for the next slot opens after them.
_SLOT_CONSUMING = frozenset(
    s for s in RunStatus if s not in (RunStatus.DEFERRED_BATTERY, RunStatus.INVALID)
)


@dataclass(frozen=True, slots=True)
class TickDeps:
    definitions: DefinitionsPort
    catalog_for: Callable[[Definitions], BackendCatalogPort]
    store: RunStorePort
    clock: ClockPort
    process: ProcessPort
    power: PowerPort
    network: NetworkPort
    notifier: NotifierPort
    paths: Paths
    launch: Callable[[str], None]
    run_id_suffix: Callable[[], str]


@dataclass(slots=True)
class TickReport:
    fired: list[str] = field(default_factory=list)
    missed: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, str] = field(default_factory=dict)
    interrupted: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    locked_out: bool = False


# --- helpers -----------------------------------------------------------------


def _notify_once(
    deps: TickDeps, *, text: str, level: str, chore: str | None = None
) -> None:
    """Post unless an unread notification already says exactly this."""
    if any(n.text == text for n in deps.store.notifications()):
        return
    post(
        deps.store,
        deps.notifier,
        at=deps.clock.now_utc(),
        level=level,
        text=text,
        chore=chore,
    )


def _check_ledger(deps: TickDeps, report: TickReport) -> int | None:
    """The ledger row count, or None when the ledger cannot be read: the
    ceilings are computed from it, so nothing may be admitted until a human
    repairs the file."""
    last = deps.store.last_tick()
    try:
        count = deps.store.ledger_count()
    except InfrastructureError as e:
        warning = f"ledger unreadable: {e}; nothing admitted this tick"
        report.warnings.append(warning)
        _notify_once(deps, text=warning, level="alert")
        return None
    if last is not None and count < last.ledger_rows:
        warning = (
            f"ledger shrank from {last.ledger_rows} rows to {count} since the last tick"
        )
        report.warnings.append(warning)
        _notify_once(deps, text=warning, level="alert")
    return count


def _interrupt_dead_runs(deps: TickDeps, ctx: Context, report: TickReport) -> None:
    now = deps.clock.now_utc()
    stale_after = timedelta(seconds=ctx.definitions.config.tick_interval_sec)
    by_name = {c.name: c for c in ctx.definitions.chores}
    for record in deps.store.records():
        reason: str | None = None
        if record.status is RunStatus.RUNNING and record.pid is not None:
            start = record.process_start if record.process_start is not None else 0.0
            if not deps.process.alive(record.pid, process_start=start):
                reason = f"process {record.pid} gone without a terminal status"
        elif record.status is RunStatus.PENDING and now - record.started > stale_after:
            reason = "never reached RUNNING within one tick interval"
        if reason is None:
            continue

        def interrupt(cur: RunRecord, *, why: str = reason) -> RunRecord:
            return cur.finish(RunStatus.INTERRUPTED, ended=now, reason=why)

        done = deps.store.transition(
            record.run_id, expected=record.status, then=interrupt
        )
        if done is None:
            continue  # the runner finished between the scan and this check
        # A runner that died before Artifacts.prepare() (resolving a secret,
        # say) left a bare record: the five artifacts and the reason are
        # written here so an INTERRUPTED run dir reads like any other.
        artifacts = Artifacts(
            deps.store, done.run_id, (), ctx.definitions.config.max_run_dir_bytes
        )
        artifacts.prepare()
        artifacts.append("errors.log", reason + "\n")
        deps.store.append_ledger(to_ledger_row(done))
        report.interrupted.append(record.run_id)
        chore = by_name.get(record.chore)
        if chore is not None:
            apply_breaker(
                deps.store,
                deps.notifier,
                chore,
                threshold=ctx.definitions.config.failure_threshold,
                at=now,
            )
        if chore is not None and RunStatus.INTERRUPTED in chore.notify_on:
            post(
                deps.store,
                deps.notifier,
                at=now,
                level="info",
                text=f"{record.chore}: INTERRUPTED: {reason}",
                run_id=record.run_id,
                chore=record.chore,
            )


def _record_invalid(
    deps: TickDeps,
    ctx: Context,
    report: TickReport,
    *,
    name: str,
    kind: Kind,
    reason: str,
) -> None:
    filed_as = invalid_record_name(name)
    if filed_as != name:
        reason = f"definition file {name!r}.md: {reason}"
    name = filed_as
    latest = next(iter(deps.store.records(chore=name)), None)
    report.invalid.append(name)
    if (
        latest is not None
        and latest.status is RunStatus.INVALID
        and latest.reason == reason
    ):
        ensure_ledgered(deps.store, latest)  # a crash may have lost its row
        return
    record = write_outcome(
        deps.store,
        run_id=mint_run_id(name, deps.clock, deps.run_id_suffix),
        chore=name,
        kind=kind,
        definition_rev=ctx.definitions.revision,
        status=RunStatus.INVALID,
        reason=reason,
        at=deps.clock.now_utc(),
        max_bytes=ctx.definitions.config.max_run_dir_bytes,
    )
    post(
        deps.store,
        deps.notifier,
        at=record.started,
        level="info",
        text=f"{name}: INVALID: {reason}",
        run_id=record.run_id,
        chore=name,
    )


def _warn_chore(deps: TickDeps, report: TickReport, chore: Chore, e: Exception) -> None:
    """An infrastructure failure while considering one chore (the launcher,
    the store) is reported as a tick warning and a notification. It is not an
    INVALID record: the definition is fine, and one broken chore never stops
    the tick."""
    text = f"{chore.name}: tick could not act: {e}"
    report.warnings.append(text)
    post(
        deps.store,
        deps.notifier,
        at=deps.clock.now_utc(),
        level="info",
        text=text,
        chore=chore.name,
    )


def _window_start(
    deps: TickDeps, chore: Chore, *, previous_tick: TickMark | None
) -> tuple[datetime, RunRecord | None]:
    """(local window start, latest record). The window opens after the newest
    slot-consuming record, else at the previous tick, else now. A chore with
    no records is therefore first seen at the previous tick: it fires at its
    next slot and never catches up across the gap before that tick."""
    latest: RunRecord | None = None
    for record in deps.store.records(chore=chore.name):
        if latest is None:
            latest = record
        if record.status in _SLOT_CONSUMING:
            return deps.clock.local_from_utc(record.started), latest
    if previous_tick is not None:
        return deps.clock.local_from_utc(previous_tick.at), latest
    return deps.clock.now_local(), latest


def _outcome(
    deps: TickDeps, ctx: Context, chore: Chore, status: RunStatus, reason: str
) -> None:
    write_outcome(
        deps.store,
        run_id=mint_run_id(chore.name, deps.clock, deps.run_id_suffix),
        chore=chore.name,
        kind=chore.kind,
        definition_rev=ctx.definitions.revision,
        status=status,
        reason=reason,
        at=deps.clock.now_utc(),
        max_bytes=ctx.definitions.config.max_run_dir_bytes,
    )


def _consider(
    deps: TickDeps,
    ctx: Context,
    host: Host,
    chore: Chore,
    report: TickReport,
    *,
    previous_tick: TickMark | None,
) -> None:
    if not chore.enabled:
        return
    errors = binding_errors(ctx, chore, forbidden=deps.paths.forbidden_for_cwd())
    if errors:
        _record_invalid(
            deps,
            ctx,
            report,
            name=chore.name,
            kind=chore.kind,
            reason="; ".join(errors),
        )
        return
    window_start, latest = _window_start(deps, chore, previous_tick=previous_tick)
    retained = latest is not None and latest.status is RunStatus.DEFERRED_BATTERY
    if retained:
        due_now = True
    else:
        verdict = due_policy(
            chore.schedule,
            window_start=window_start,
            now=deps.clock.now_local(),
            grace=timedelta(seconds=ctx.definitions.config.missed_grace_sec),
            catch_up=chore.catch_up,
        )
        if verdict.missed and (verdict.fire is None or not verdict.caught_up):
            report.missed[chore.name] = verdict.missed
            _outcome(
                deps,
                ctx,
                chore,
                RunStatus.MISSED,
                f"{verdict.missed} slot(s) older than the missed grace; not replayed",
            )
        elif verdict.missed and verdict.caught_up:
            report.missed[chore.name] = verdict.missed
            _outcome(
                deps,
                ctx,
                chore,
                RunStatus.MISSED,
                f"{verdict.missed} slot(s) older than grace; catch_up fires one run",
            )
        due_now = verdict.fire is not None
    if not due_now:
        return
    admission, _spec = admit(ctx, chore, host)
    if admission.decision is Decision.ADMIT:
        report.fired.append(chore.name)
        deps.launch(chore.name)
        return
    if admission.record_status is None:
        return
    if admission.record_status is RunStatus.DEFERRED_BATTERY and retained:
        return  # one record per retained slot, not one per tick
    report.skipped[chore.name] = admission.reason or admission.record_status.value
    _outcome(deps, ctx, chore, admission.record_status, admission.reason or "")


# --- the use case ------------------------------------------------------------


def tick(deps: TickDeps) -> TickReport:
    report = TickReport()
    with deps.store.tick_lock() as acquired:
        if not acquired:
            report.locked_out = True
            return report
        previous_tick = deps.store.last_tick()
        ledger_rows = _check_ledger(deps, report)
        if ledger_rows is None:
            # Liveness is still marked (the scheduler IS running), with the
            # previous count so the next tick does not report a shrink.
            rows = previous_tick.ledger_rows if previous_tick is not None else 0
            deps.store.mark_tick(TickMark(at=deps.clock.now_utc(), ledger_rows=rows))
            return report
        # The mark is written once, AFTER the pass: a pass that dies half way
        # leaves the previous mark in place, so the next tick replays its
        # window instead of treating the dead pass as done.
        ctx = load_context(deps.definitions, deps.catalog_for)
        host = Host(deps.store, deps.process, deps.clock, deps.power, deps.network)
        for error in [*ctx.definitions.errors, *ctx.catalog.errors]:
            report.warnings.append(error)
            _notify_once(deps, text=f"definitions: {error}", level="info")
        if ctx.definitions.config_error is not None:
            # Defaults would stand in for the global ceiling and the tick
            # interval: admit nothing until config.yaml parses again.
            report.warnings.append("config.yaml invalid: nothing admitted this tick")
            deps.store.mark_tick(
                TickMark(at=deps.clock.now_utc(), ledger_rows=deps.store.ledger_count())
            )
            return report
        for invalid in ctx.definitions.invalid:
            _record_invalid(
                deps,
                ctx,
                report,
                name=invalid.name,
                kind=invalid.kind,
                reason=invalid.error,
            )
        _interrupt_dead_runs(deps, ctx, report)
        for chore in ctx.definitions.chores:
            try:
                _consider(deps, ctx, host, chore, report, previous_tick=previous_tick)
            except DomainError as e:  # a rule violated: the definition is wrong
                _record_invalid(
                    deps, ctx, report, name=chore.name, kind=chore.kind, reason=str(e)
                )
            except ChoresError as e:  # a mechanism failed: the chore stays valid
                _warn_chore(deps, report, chore, e)
        deps.store.mark_tick(
            TickMark(at=deps.clock.now_utc(), ledger_rows=deps.store.ledger_count())
        )
    return report
