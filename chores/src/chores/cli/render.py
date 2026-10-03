"""Rendering StatusView and records as tables or JSON (CLI and TUI share it).

Times: records, ticks and notifications carry naive UTC (ports/host.py);
only a chore's `next_due` is local. JSON keeps the stored values. The text
surfaces print every time in local wall-clock time, so the caller passes
the clock's `local_from_utc` as `local` (issue #393).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum

from chores.adapters.fs_store import record_to_json
from chores.application.status import ChoreStatus, RunSummary, StatusView
from chores.domain.run import RunRecord

Localize = Callable[[datetime], datetime]


def _jsonable(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return {k: _jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | frozenset | set):
        return [_jsonable(v) for v in value]
    return value


def status_json(view: StatusView) -> str:
    payload = _jsonable(view)
    assert isinstance(payload, dict)
    payload["needs_attention"] = view.needs_attention
    return json.dumps(payload, indent=1, sort_keys=True)


def records_json(records: Sequence[RunRecord]) -> str:
    return json.dumps([record_to_json(r) for r in records], indent=1)


def _when(at: datetime | None) -> str:
    """A local wall-clock time as the surfaces print it."""
    return "-" if at is None else at.strftime("%m-%d %H:%M")


def _utc_when(at: datetime | None, local: Localize) -> str:
    """A stored UTC time, printed in local wall-clock time."""
    return "-" if at is None else _when(local(at))


def _run_cell(summary: RunSummary | None, local: Localize) -> str:
    if summary is None:
        return "-"
    return (
        f"{summary.status.value} {_utc_when(summary.ended or summary.started, local)}"
    )


def _usage_cell(summary: RunSummary | None) -> str:
    if summary is None or summary.usage is None:
        return "-"
    u = summary.usage
    usd = f" ${u.usd:.3f}" if u.usd is not None else ""
    return f"{u.tokens}t{usd} {u.seconds:.0f}s"


def table(rows: Sequence[Sequence[str]], header: Sequence[str]) -> str:
    widths = [len(h) for h in header]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    lines = [fmt.format(*header), fmt.format(*("-" * w for w in widths))]
    lines.extend(fmt.format(*row) for row in rows)
    return "\n".join(lines)


def _chore_row(c: ChoreStatus, *, local: Localize) -> list[str]:
    state = (
        "invalid"
        if c.invalid
        else ("paused" if c.paused_by else ("on" if c.enabled else "off"))
    )
    if c.running:
        state = "RUNNING"
    return [
        c.name,
        state,
        c.schedule,
        _when(c.next_due)
        + (" armed" if c.armed is not None and c.next_due == c.armed.start_at else ""),
        _run_cell(c.last_run, local),
        _usage_cell(c.last_run),
        _run_cell(c.last_failure, local),
    ]


def status_text(view: StatusView, *, local: Localize) -> str:
    out: list[str] = []
    if view.paused:
        out.append(f"PAUSED: {view.paused}")
    sched = view.scheduler
    installed = {True: "installed", False: "NOT INSTALLED", None: "install unknown"}[
        sched.installed
    ]
    tick = _utc_when(sched.last_tick, local)
    out.append(
        f"scheduler: {installed}; last tick {tick}{' (STALE)' if sched.stale else ''}; "
        f"ledger rows {sched.ledger_rows}"
    )
    out.append("")
    out.append(
        table(
            [_chore_row(c, local=local) for c in view.chores],
            ["chore", "state", "schedule", "next", "last run", "usage", "last failure"],
        )
    )
    out.append("")
    usage_rows = []
    for scope in view.usage:
        u, cap = scope.usage, scope.ceiling
        usd = f"${u.usd:.3f}" if u.usd is not None else "-"
        caps = (
            ", ".join(f"{d}<={getattr(cap, d)}" for d in sorted(cap.dimensions()))
            or "-"
        )
        usage_rows.append([scope.scope, str(u.tokens), usd, str(u.turns or 0), caps])
    out.append(table(usage_rows, ["24h usage", "tokens", "usd", "turns", "ceilings"]))
    for c in view.chores:
        if c.invalid:
            out.append(f"INVALID {c.name}: {c.invalid}")
    for w in view.warnings:
        out.append(f"WARNING: {w}")
    if view.notifications:
        out.append("")
        out.append("notifications:")
        for n in view.notifications:
            out.append(f"  [{n.id}] {n.level} {_utc_when(n.ts, local)} {n.text}")
    return "\n".join(out)


def runs_text(records: Sequence[RunRecord], *, local: Localize) -> str:
    rows = [
        [
            r.run_id,
            r.status.value,
            _utc_when(r.started, local),
            _utc_when(r.ended, local),
            _usage_cell(RunSummary.of(r)),
            (r.reason or "")[:60],
        ]
        for r in records
    ]
    return table(rows, ["run", "status", "started", "ended", "usage", "reason"])
