"""Shared application helpers used by both use cases (run and tick):
loading definitions with a catalog, finding a chore, live-run detection,
the rolling ceiling window, admission facts, and outcome recording."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from chores.domain.budget import Usage
from chores.domain.chore import BackendSpec, Chore, check_bindings
from chores.domain.kinds import Kind
from chores.domain.policies import (
    AdmissionFacts,
    AdmissionVerdict,
    Decision,
    LedgerUsage,
    admission_policy,
    ceiling_policy,
)
from chores.domain.run import Billing, RunRecord, RunStatus, new_run_id, to_ledger_row
from chores.ports.backends import BackendCatalogPort
from chores.ports.definitions import Definitions, DefinitionsPort, InvalidDefinition
from chores.ports.host import ClockPort, NetworkPort, NotifierPort, PowerPort
from chores.ports.process import ProcessPort
from chores.ports.store import ARTIFACTS, Notification, RunStorePort

CEILING_WINDOW = timedelta(hours=24)
PROBE_TIMEOUT_SEC = 3.0


@dataclass(frozen=True, slots=True)
class Context:
    definitions: Definitions
    catalog: BackendCatalogPort


def load_context(
    definitions: DefinitionsPort,
    catalog_for: Callable[[Definitions], BackendCatalogPort],
) -> Context:
    defs = definitions.load()
    return Context(definitions=defs, catalog=catalog_for(defs))


_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def invalid_record_name(stem: str) -> str:
    """The ``chore`` under which an INVALID outcome for definition file
    ``<stem>.md`` is filed. A stem that is already a chore name is used as is;
    anything else (``foo.bar``, ``My Chore``) is folded to ``INVALID-<safe>``:
    a path-safe run-id segment that, being uppercase, can never collide with
    a real chore's name."""
    if _NAME_RE.match(stem):
        return stem
    safe = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-") or "unnamed"
    return f"INVALID-{safe}"


def find_chore(defs: Definitions, name: str) -> Chore | InvalidDefinition | None:
    for chore in defs.chores:
        if chore.name == name:
            return chore
    for invalid in defs.invalid:
        if invalid.name == name:
            return invalid
    return None


def binding_errors(
    ctx: Context, chore: Chore, *, forbidden: Sequence[str]
) -> list[str]:
    backend = ctx.catalog.spec(chore.backend) if chore.backend else None
    return check_bindings(
        chore,
        backend=backend,
        global_ceiling=ctx.definitions.config.ceiling,
        forbidden_paths=forbidden,
    )


def live_running(
    store: RunStorePort,
    process: ProcessPort,
    chore: str,
    *,
    now_utc: datetime,
    pending_grace: timedelta,
) -> RunRecord | None:
    """The record that counts as live: a RUNNING one whose process is really
    alive, or a PENDING one younger than ``pending_grace`` (the runner writes
    PENDING before it resolves secrets and spawns; a stale PENDING is the
    tick's to interrupt, not a reason to skip)."""
    for record in store.records(chore=chore):
        if record.status is RunStatus.RUNNING and record.pid is not None:
            start = record.process_start if record.process_start is not None else 0.0
            if process.alive(record.pid, process_start=start):
                return record
        elif record.status is RunStatus.PENDING:
            if now_utc - record.started <= pending_grace:
                return record
    return None


def ledger_window(store: RunStorePort, *, now_utc: datetime) -> list[LedgerUsage]:
    rows: list[LedgerUsage] = []
    for row in store.ledger_rows(since=now_utc - CEILING_WINDOW):
        billing = row.get("billing")
        rows.append(
            LedgerUsage(
                chore=str(row.get("chore")),
                backend=None if row.get("backend") is None else str(row.get("backend")),
                billing=Billing(str(billing)) if billing else None,
                usage=Usage(
                    tokens_in=int(str(row.get("tokens_in", 0))),
                    tokens_out=int(str(row.get("tokens_out", 0))),
                    seconds=float(str(row.get("seconds", 0.0))),
                    usd=None if row.get("usd") is None else float(str(row.get("usd"))),
                    turns=None
                    if row.get("turns") is None
                    else int(str(row.get("turns"))),
                ),
            )
        )
    return rows


@dataclass(frozen=True, slots=True)
class Host:
    store: RunStorePort
    process: ProcessPort
    clock: ClockPort
    power: PowerPort
    network: NetworkPort


def admit(
    ctx: Context, chore: Chore, host: Host, *, force: bool = False
) -> tuple[AdmissionVerdict, BackendSpec | None]:
    """Gather the admission facts for one chore and decide."""
    spec = ctx.catalog.spec(chore.backend) if chore.backend else None
    offline = False
    if chore.needs_network(spec) and chore.backend:
        url = ctx.catalog.probe_url(chore.backend)
        if url is not None:
            offline = not host.network.reachable(url, timeout_sec=PROBE_TIMEOUT_SEC)
    ceiling = ceiling_policy(
        ledger_window(host.store, now_utc=host.clock.now_utc()),
        chore=chore,
        backend=spec,
        global_ceiling=ctx.definitions.config.ceiling,
        count_subscription_usd=ctx.definitions.config.count_subscription_usd,
    )
    running = live_running(
        host.store,
        host.process,
        chore.name,
        now_utc=host.clock.now_utc(),
        pending_grace=timedelta(seconds=ctx.definitions.config.tick_interval_sec),
    )
    facts = AdmissionFacts(
        enabled=chore.enabled,
        globally_paused=host.store.paused(),
        chore_paused=host.store.chore_paused(chore.name),
        running_run_id=running.run_id if running else None,
        on_battery=host.power.on_battery() if chore.defer_on_battery else False,
        defer_on_battery=chore.defer_on_battery,
        offline=offline,
        requires_network=chore.needs_network(spec),
        ceiling_refusal=ceiling.reason if ceiling.decision is Decision.REFUSE else None,
        force=force,
    )
    return admission_policy(facts), spec


def write_outcome(
    store: RunStorePort,
    *,
    run_id: str,
    chore: str,
    kind: Kind,
    definition_rev: str,
    status: RunStatus,
    reason: str,
    at: datetime,
    definition: str | None = None,
) -> RunRecord:
    """A tick-written outcome (a refusal, MISSED, INVALID): record, the five
    artifacts every run directory carries (design: complete record) with the
    definition snapshot when the caller has one, and the ledger row."""
    record = RunRecord.outcome(
        run_id=run_id,
        chore=chore,
        kind=kind,
        definition_rev=definition_rev,
        status=status,
        reason=reason,
        at=at,
    )
    store.write_record(record)
    for name in ARTIFACTS:
        store.append_artifact(run_id, name, "")
    if definition is not None:
        store.append_artifact(run_id, "definition.md", definition)
    if reason:
        store.append_artifact(run_id, "errors.log", reason + "\n")
    store.append_ledger(to_ledger_row(record))
    return record


def post(
    store: RunStorePort,
    notifier: NotifierPort,
    *,
    at: datetime,
    level: str,
    text: str,
    run_id: str | None = None,
    chore: str | None = None,
) -> Notification:
    """The one place a notification is queued and, for level=alert, the
    desktop is told: every producer (runner, tick, `chores notify`) goes
    through here so an alert is raised exactly once."""
    posted = store.notify(at=at, level=level, text=text, run_id=run_id, chore=chore)
    if level == "alert":
        notifier.alert(title="chores", text=text)
    return posted


def mint_run_id(chore: str, clock: ClockPort, suffix: Callable[[], str]) -> str:
    return new_run_id(chore, at=clock.now_utc(), suffix=suffix())
