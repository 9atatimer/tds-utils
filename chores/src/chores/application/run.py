"""The run use case (CHORES.DESIGN.md Subsystem 3): admit, resolve, execute,
record. The only path that starts a run, so admission lives here as well
as in tick. Orchestrates ports only; every decision is a domain policy.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import datetime

from chores.application.context import (
    Artifacts,
    Context,
    Host,
    admit,
    apply_breaker,
    binding_errors,
    end_arming,
    find_chore,
    invalid_record_name,
    load_context,
    mint_run_id,
    note_false_breaker,
    post,
    write_outcome,
)
from chores.application.paths import Paths
from chores.domain.budget import Budget, Ceiling, SpendAction, Usage, spend_policy
from chores.domain.chore import BackendSpec, Chore
from chores.domain.errors import ChoresError
from chores.domain.kinds import Kind
from chores.domain.policies import Decision, redact
from chores.domain.run import Billing, RunRecord, RunStatus, to_ledger_row
from chores.ports.agent import AgentTask, ProcessIdentity
from chores.ports.backends import BackendCatalogPort
from chores.ports.completion import CompletionRequest
from chores.ports.definitions import Definitions, DefinitionsPort, InvalidDefinition
from chores.ports.errors import (
    BackendError,
    BackendTimeout,
    ProcessError,
    SecretUnavailable,
    Unreachable,
)
from chores.ports.host import (
    ClockPort,
    NetworkPort,
    NotifierPort,
    PowerPort,
    SecretsPort,
)
from chores.ports.process import ProcessPort, ProcessRequest
from chores.ports.store import RunStorePort, WorkspacesPort

# USER: the Claude CLI looks its subscription login up in the macOS keychain
# by user; with only HOME it reports "Not logged in" (issue #406).
_INHERITED_KEYS = ("PATH", "HOME", "LANG", "USER")


@dataclass(frozen=True, slots=True)
class RunDeps:
    definitions: DefinitionsPort
    catalog_for: Callable[[Definitions], BackendCatalogPort]
    store: RunStorePort
    clock: ClockPort
    process: ProcessPort
    secrets: SecretsPort
    power: PowerPort
    network: NetworkPort
    notifier: NotifierPort
    workspaces: WorkspacesPort
    paths: Paths
    inherited_env: Mapping[str, str]
    run_id_suffix: Callable[[], str]


@dataclass(frozen=True, slots=True)
class RunPlan:
    chore: str
    kind: str
    backend: str | None
    model: str | None
    cwd: str
    env_names: Sequence[str]
    secret_names: Sequence[str]
    argv: Sequence[str] | None
    budget: Budget
    admission: str
    admission_reason: str | None
    port: str | None = None
    """The execution port the kind resolves to (completion / agent), None for
    a command chore."""
    ceilings: Mapping[str, Ceiling] = field(default_factory=dict)
    """Every ceiling that applies, by scope: chore, backend, global (only
    scopes that cap at least one dimension are present)."""


@dataclass(frozen=True, slots=True)
class RunOutcome:
    record: RunRecord | None
    message: str
    plan: RunPlan | None = None


class RunLost(ChoresError):
    """The tick recorded this run as INTERRUPTED (a stale PENDING) before the
    runner reached RUNNING: the runner stops, and writes nothing more."""


@dataclass
class _Execution:
    status: RunStatus
    reason: str | None
    usage: Usage
    backend: str | None = None
    model: str | None = None
    billing: Billing | None = None
    exit_code: int | None = None
    output_truncated: bool = False


# --- helpers -----------------------------------------------------------------


def _resolve_secrets(
    chore: Chore, ctx: Context, deps: RunDeps
) -> tuple[dict[str, str], str | None, str | None]:
    """(env name -> value, backend credential, failure reason)."""
    timeout = ctx.definitions.config.secret_timeout_sec
    values: dict[str, str] = {}
    for env_name, ref in (chore.secrets or {}).items():
        try:
            values[env_name] = deps.secrets.resolve(ref, timeout_sec=timeout)
        except SecretUnavailable as e:
            return values, None, f"secret unavailable: {env_name} ({ref}): {e}"
    credential: str | None = None
    cred_ref = ctx.catalog.credential_ref(chore.backend) if chore.backend else None
    if cred_ref is not None:
        try:
            credential = deps.secrets.resolve(cred_ref, timeout_sec=timeout)
        except SecretUnavailable as e:
            return (
                values,
                None,
                f"secret unavailable: backend credential ({cred_ref}): {e}",
            )
    return values, credential, None


def _build_env(
    chore: Chore,
    *,
    run_id: str,
    secrets: Mapping[str, str],
    inherited: Mapping[str, str],
) -> dict[str, str]:
    env = {k: inherited[k] for k in _INHERITED_KEYS if k in inherited}
    env.update(chore.env or {})
    env.update(secrets)
    env["CHORES_RUN_ID"] = run_id
    env["CHORES_CHORE"] = chore.name
    env["CHORES_BUDGET_SECONDS"] = str(chore.budget.seconds)
    for dim in ("tokens", "usd", "turns"):
        value = getattr(chore.budget, dim)
        if value is not None:
            env[f"CHORES_BUDGET_{dim.upper()}"] = str(value)
    env["CHORES_SECRET_NAMES"] = ",".join(sorted(secrets))
    return env


def _cwd(chore: Chore, deps: RunDeps) -> str:
    return chore.cwd if chore.cwd is not None else deps.workspaces.ensure(chore.name)


def ctx_store_kill_requested(artifacts: Artifacts) -> bool:
    return artifacts.store.kill_requested(artifacts.run_id)


def _map_error(error: BackendError, *, needs_network: bool) -> tuple[RunStatus, str]:
    if isinstance(error, Unreachable) and needs_network:
        return RunStatus.OFFLINE, str(error)
    if isinstance(error, BackendTimeout):
        return RunStatus.TIMED_OUT, str(error)
    return RunStatus.FAILED, str(error)


def _execute_prompt(
    chore: Chore,
    spec: BackendSpec,
    ctx: Context,
    *,
    credential: str | None,
    artifacts: Artifacts,
) -> _Execution:
    model = chore.model or spec.default_model or ""
    try:
        port = ctx.catalog.completion(spec.name, credential=credential)
    except (KeyError, ValueError) as e:
        reason = f"backend {spec.name!r} misconfigured: {e}"
        artifacts.append("errors.log", reason + "\n")
        return _Execution(RunStatus.FAILED, reason, Usage(0, 0, 0.0), backend=spec.name)
    artifacts.event({"role": "user", "content": chore.body, "model": model})
    try:
        response = port.complete(
            CompletionRequest(
                prompt=chore.body,
                model=model,
                timeout_sec=chore.budget.seconds,
                max_output_tokens=chore.budget.tokens,
            )
        )
    except BackendError as e:
        status, reason = _map_error(e, needs_network=chore.needs_network(spec))
        artifacts.append("errors.log", reason + "\n")
        return _Execution(
            status, reason, Usage(0, 0, 0.0), backend=spec.name, model=model
        )
    artifacts.event(
        {"role": "assistant", "content": response.text, "provider": response.provider}
    )
    return _Execution(
        RunStatus.SUCCEEDED,
        None,
        Usage(
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
            seconds=response.latency_sec,
            usd=response.usd,
        ),
        backend=spec.name,
        model=response.model,
        billing=response.billing,
    )


def _execute_agent(
    chore: Chore,
    spec: BackendSpec,
    ctx: Context,
    *,
    credential: str | None,
    env: Mapping[str, str],
    cwd: str,
    artifacts: Artifacts,
    on_start: Callable[[ProcessIdentity], None],
    own_identity: Callable[[], ProcessIdentity],
) -> _Execution:
    model = chore.model or spec.default_model or ""
    try:
        port = ctx.catalog.agent(spec.name, credential=credential)
    except (KeyError, ValueError) as e:
        reason = f"backend {spec.name!r} misconfigured: {e}"
        artifacts.append("errors.log", reason + "\n")
        return _Execution(RunStatus.FAILED, reason, Usage(0, 0, 0.0), backend=spec.name)
    artifacts.event({"role": "user", "content": chore.body, "model": model})
    try:
        result = port.run(
            AgentTask(
                body=chore.body,
                model=model,
                cwd=cwd,
                allowed_tools=chore.effective_tools(spec),
                max_turns=chore.budget.turns,
                timeout_sec=chore.budget.seconds,
                env=env,
                kill_grace_sec=ctx.definitions.config.kill_grace_sec,
                max_output_bytes=ctx.definitions.config.max_run_dir_bytes,
            ),
            on_start=on_start,
        )
    except ProcessError as e:
        on_start(own_identity())
        artifacts.append("errors.log", str(e) + "\n")
        return _Execution(
            RunStatus.FAILED, str(e), Usage(0, 0, 0.0), backend=spec.name, model=model
        )
    except BackendError as e:
        if ctx_store_kill_requested(artifacts):
            artifacts.append("errors.log", str(e) + "\n")
            return _Execution(
                RunStatus.KILLED,
                "killed by chores kill",
                Usage(0, 0, 0.0),
                backend=spec.name,
                model=model,
            )
        status, reason = _map_error(e, needs_network=chore.needs_network(spec))
        artifacts.append("errors.log", reason + "\n")
        return _Execution(
            status, reason, Usage(0, 0, 0.0), backend=spec.name, model=model
        )
    for event in result.events:
        artifacts.event(event)
    artifacts.event({"role": "assistant", "content": result.text})
    usage = Usage(
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        seconds=0.0,
        usd=result.usd,
        turns=result.turns,
        cpu_seconds=result.cpu_seconds,
    )
    if ctx_store_kill_requested(artifacts):
        # first: a killed child exits nonzero without raising, or comes back
        # through the timeout path if it ignored SIGTERM; the marker decides
        return _Execution(
            RunStatus.KILLED,
            "killed by chores kill",
            usage,
            backend=spec.name,
            model=model,
            billing=result.billing,
            exit_code=result.exit_code,
            output_truncated=result.output_truncated,
        )
    if result.timed_out:
        return _Execution(
            RunStatus.TIMED_OUT,
            f"timed out after {chore.budget.seconds}s",
            usage,
            backend=spec.name,
            model=model,
            billing=result.billing,
            exit_code=result.exit_code,
            output_truncated=result.output_truncated,
        )
    if result.exit_code != 0:
        return _Execution(
            RunStatus.FAILED,
            f"exit {result.exit_code}",
            usage,
            backend=spec.name,
            model=model,
            billing=result.billing,
            exit_code=result.exit_code,
            output_truncated=result.output_truncated,
        )
    return _Execution(
        RunStatus.SUCCEEDED,
        None,
        usage,
        backend=spec.name,
        model=model,
        billing=result.billing,
        exit_code=0,
        output_truncated=result.output_truncated,
    )


def _execute_command(
    chore: Chore,
    deps: RunDeps,
    ctx: Context,
    *,
    env: Mapping[str, str],
    cwd: str,
    artifacts: Artifacts,
    on_start: Callable[[ProcessIdentity], None],
) -> _Execution:
    assert chore.command is not None
    try:
        running = deps.process.spawn(
            ProcessRequest(
                argv=chore.command,
                cwd=cwd,
                env=env,
                timeout_sec=chore.budget.seconds,
                kill_grace_sec=ctx.definitions.config.kill_grace_sec,
                max_output_bytes=ctx.definitions.config.max_run_dir_bytes,
            )
        )
    except ProcessError as e:
        on_start(deps.process.own_identity())
        artifacts.append("errors.log", str(e) + "\n")
        return _Execution(RunStatus.FAILED, str(e), Usage(0, 0, 0.0))
    on_start(running.identity)
    result = running.wait()
    if result.stdout:
        artifacts.append("stdout.log", result.stdout)
    if result.stderr:
        artifacts.append("stderr.log", result.stderr)
    usage = Usage(0, 0, result.seconds, cpu_seconds=result.cpu_seconds)
    lost = result.output_truncated  # the adapter dropped output past its cap
    if deps.store.kill_requested(artifacts.run_id):
        # first: a command that ignored SIGTERM comes back through the
        # timeout path, and the operator's kill is still the outcome
        return _Execution(
            RunStatus.KILLED,
            "killed by chores kill",
            usage,
            exit_code=result.exit_code,
            output_truncated=lost,
        )
    if result.timed_out:
        return _Execution(
            RunStatus.TIMED_OUT,
            f"timed out after {chore.budget.seconds}s",
            usage,
            exit_code=result.exit_code,
            output_truncated=lost,
        )
    if result.exit_code != 0:
        tail = result.stderr.strip()[-200:]
        return _Execution(
            RunStatus.FAILED,
            f"exit {result.exit_code}: {tail}".rstrip(": "),
            usage,
            exit_code=result.exit_code,
            output_truncated=lost,
        )
    return _Execution(
        RunStatus.SUCCEEDED, None, usage, exit_code=0, output_truncated=lost
    )


def _finish(
    record: RunRecord,
    execution: _Execution,
    chore: Chore,
    deps: RunDeps,
    ctx: Context,
    *,
    started_utc: datetime,
    artifacts: Artifacts,
) -> RunRecord:
    ended = deps.clock.now_utc()
    usage = Usage(
        tokens_in=execution.usage.tokens_in,
        tokens_out=execution.usage.tokens_out,
        seconds=max(execution.usage.seconds, (ended - started_utc).total_seconds()),
        usd=execution.usage.usd,
        turns=execution.usage.turns,
        cpu_seconds=execution.usage.cpu_seconds,
        disk_bytes=deps.store.run_dir_bytes(record.run_id),
    )
    status = execution.status
    reason = redact(execution.reason, artifacts.secrets) if execution.reason else None
    if status is RunStatus.SUCCEEDED:
        # Time is bounded by the adapters (timeouts); the wall clock here includes
        # secret resolution and snapshotting, so it must not flip a success.
        measured = Usage(
            tokens_in=usage.tokens_in,
            tokens_out=usage.tokens_out,
            seconds=execution.usage.seconds,
            usd=usage.usd,
            turns=usage.turns,
        )
        verdict = spend_policy(measured, chore.budget)
        if verdict.action is SpendAction.STOP:
            status, reason = RunStatus.BUDGET_EXCEEDED, verdict.reason
    record = record.with_usage(
        usage,
        backend=execution.backend,
        model=execution.model,
        billing=execution.billing,
        exit_code=execution.exit_code,
    )
    if artifacts.truncated or execution.output_truncated:
        record = record.truncate()
    final = record.finish(status, ended=ended, reason=reason)
    record = final
    done = deps.store.transition(
        record.run_id, expected=RunStatus.RUNNING, then=lambda _current: final
    )
    if done is None:
        # The tick closed this run on liveness alone: the child had exited and
        # the runner was still finishing. The runner holds the true outcome, so
        # it wins (issue #298). Under the chore's lock, which the tick holds
        # while it closes a run and publishes about it, so the amendment lands
        # wholly after that. The real row goes first, so the spend is never
        # uncounted, and it names the zero-usage INTERRUPTED row it supersedes.
        with deps.store.chore_lock(chore.name):
            current = deps.store.read_record(record.run_id)
            if current is None or current.status is not RunStatus.INTERRUPTED:
                return current if current is not None else record
            deps.store.append_ledger(
                to_ledger_row(record, amends=RunStatus.INTERRUPTED)
            )
            deps.store.transition(
                record.run_id,
                expected=RunStatus.INTERRUPTED,
                then=lambda _current: final,
            )
        artifacts.append(
            "errors.log",
            f"outcome {status.value} recorded over the tick's INTERRUPTED: the "
            "child exited before the runner finished\n",
        )
        note_false_breaker(
            deps.store,
            deps.notifier,
            chore,
            threshold=ctx.definitions.config.failure_threshold,
            at=ended,
        )
    else:
        deps.store.append_ledger(to_ledger_row(record))
    if status in chore.notify_on:
        level = "alert" if status is RunStatus.BUDGET_EXCEEDED else "info"
        post(
            deps.store,
            deps.notifier,
            at=ended,
            level=level,
            text=f"{chore.name}: {status.value}: {reason or ''}".rstrip(": "),
            run_id=record.run_id,
            chore=chore.name,
        )
    apply_breaker(
        deps.store,
        deps.notifier,
        chore,
        threshold=ctx.definitions.config.failure_threshold,
        at=ended,
    )
    return record


# --- the use case ------------------------------------------------------------


def _late_sec(record: RunRecord, started: datetime, *, grace_sec: int) -> int | None:
    """Seconds past ``start_at`` when that exceeds the missed grace, else None."""
    if record.start_at is None:
        return None
    late = int((started - record.start_at).total_seconds())
    return late if late > grace_sec else None


def run_chore(
    name: str,
    deps: RunDeps,
    *,
    force: bool = False,
    dry_run: bool = False,
    armed_run_id: str | None = None,
) -> RunOutcome:
    """``armed_run_id``: the tick fires an ARMED record by name; the run then
    takes over that record's id and directory (CHORES-ONE-TIME.DESIGN.md)."""
    if armed_run_id is not None:
        armed = deps.store.read_record(armed_run_id)
        if armed is None or armed.chore != name or armed.status is not RunStatus.ARMED:
            state = "missing" if armed is None else armed.status.value
            return RunOutcome(armed, f"{name}: {armed_run_id} is not armed ({state})")
    ctx = load_context(deps.definitions, deps.catalog_for)
    if ctx.definitions.config_error is not None:
        return RunOutcome(None, f"refused: {ctx.definitions.config_error}")
    host = Host(deps.store, deps.process, deps.clock, deps.power, deps.network)
    found = find_chore(ctx.definitions, name)
    kind = found.kind if found is not None else Kind.UNKNOWN  # never a false one
    if found is None:
        return RunOutcome(None, f"no chore named {name!r}")
    errors = (
        [found.error]
        if isinstance(found, InvalidDefinition)
        else binding_errors(ctx, found, forbidden=deps.paths.forbidden_for_cwd())
    )
    if errors and dry_run:
        return RunOutcome(None, f"{name} is invalid: {'; '.join(errors)}")
    if errors:
        filed_as = invalid_record_name(name)
        if filed_as != name:
            errors = [f"definition file {name!r}.md: {e}" for e in errors]
        record = write_outcome(
            deps.store,
            run_id=mint_run_id(filed_as, deps.clock, deps.run_id_suffix),
            chore=filed_as,
            kind=kind,
            definition_rev=ctx.definitions.revision,
            status=RunStatus.INVALID,
            reason="; ".join(errors),
            at=deps.clock.now_utc(),
            max_bytes=ctx.definitions.config.max_run_dir_bytes,
        )
        post(
            deps.store,
            deps.notifier,
            at=record.started,
            level="info",
            text=f"{name}: INVALID: {record.reason}",
            run_id=record.run_id,
            chore=name,
        )
        return RunOutcome(record, f"{name} is invalid: {record.reason}")
    chore = found
    assert isinstance(chore, Chore)
    # Admission and the PENDING write are one critical section per chore:
    # two runners of the same chore serialise here, so the second sees the
    # first's young PENDING record as live and is SKIPPED_OVERLAP. A
    # ceiling-bound chore also takes the store-wide lock: the PENDING record
    # carries the declared budget, and a runner of another chore must not
    # read the headroom before it is reserved (issue #283).
    with ExitStack() as reservation:
        if not dry_run:
            reservation.enter_context(deps.store.chore_lock(name))
            if chore.kind is not Kind.COMMAND:
                reservation.enter_context(deps.store.admission_lock())
        verdict, spec = admit(ctx, chore, host, force=force)
        cwd = (
            _cwd(chore, deps)
            if not dry_run or chore.cwd
            else (chore.cwd or "<workspace>")
        )
        if dry_run:
            plan = RunPlan(
                chore=chore.name,
                kind=chore.kind.value,
                backend=chore.backend,
                model=chore.model or (spec.default_model if spec else None),
                cwd=cwd,
                env_names=sorted(
                    _build_env(
                        chore,
                        run_id="<run-id>",
                        secrets={},
                        inherited=deps.inherited_env,
                    )
                ),
                secret_names=sorted(chore.secrets or {}),
                argv=chore.command,
                budget=chore.budget,
                admission=verdict.decision.name
                if verdict.decision is Decision.ADMIT
                else "SKIP",
                port=chore.port.value if chore.port else None,
                ceilings={
                    scope: ceiling
                    for scope, ceiling in (
                        ("chore", chore.ceiling),
                        ("backend", spec.ceiling if spec else Ceiling()),
                        ("global", ctx.definitions.config.ceiling),
                    )
                    if ceiling.dimensions()
                },
                admission_reason=verdict.reason,
            )
            return RunOutcome(None, "dry run", plan)
        run_id = armed_run_id or mint_run_id(name, deps.clock, deps.run_id_suffix)
        if verdict.decision is not Decision.ADMIT and armed_run_id is not None:
            armed_now = deps.store.read_record(armed_run_id)
            ended = (
                end_arming(
                    deps.store,
                    armed_now,
                    verdict.record_status or RunStatus.SKIPPED_PAUSED,
                    at=deps.clock.now_utc(),
                    reason=verdict.reason or "",
                )
                if armed_now is not None
                and armed_now.status is RunStatus.ARMED
                and verdict.record_status is not RunStatus.DEFERRED_BATTERY
                else None
            )
            return RunOutcome(ended or armed_now, f"{name}: refused: {verdict.reason}")
        if verdict.decision is not Decision.ADMIT:
            if verdict.record_status is None:
                return RunOutcome(None, f"{name}: {verdict.reason}")
            record = write_outcome(
                deps.store,
                run_id=run_id,
                chore=name,
                kind=chore.kind,
                definition_rev=ctx.definitions.revision,
                status=verdict.record_status,
                reason=verdict.reason or "",
                at=deps.clock.now_utc(),
                max_bytes=ctx.definitions.config.max_run_dir_bytes,
            )
            return RunOutcome(
                record, f"{name}: {verdict.record_status.value}: {verdict.reason}"
            )

        started_utc = deps.clock.now_utc()
        if armed_run_id is not None:
            grace = ctx.definitions.config.missed_grace_sec
            fired = deps.store.transition(
                armed_run_id,
                expected=RunStatus.ARMED,
                then=lambda current: current.fire(
                    started=started_utc,
                    definition_rev=ctx.definitions.revision,
                    late_sec=_late_sec(current, started_utc, grace_sec=grace),
                    budget=chore.budget,
                    backend=spec.name if spec else None,
                    billing=spec.billing if spec else None,
                ),
            )
            if fired is None:  # cancelled (or taken) between the tick and now
                return RunOutcome(
                    deps.store.read_record(armed_run_id),
                    f"{name}: {armed_run_id} is no longer armed",
                )
            record = fired
        else:
            record = RunRecord.pending(
                run_id=run_id,
                chore=name,
                kind=chore.kind,
                definition_rev=ctx.definitions.revision,
                started=started_utc,
                budget=chore.budget,
                backend=spec.name if spec else None,
                billing=spec.billing if spec else None,
            )
            deps.store.write_record(record)

    secret_values, credential, failure = _resolve_secrets(chore, ctx, deps)
    redaction = [*secret_values.values(), *([credential] if credential else [])]
    artifacts = Artifacts(
        deps.store, run_id, redaction, ctx.definitions.config.max_run_dir_bytes
    )
    artifacts.prepare()
    source = ctx.definitions.sources.get(name)  # the text this Chore came from
    if source is not None:
        artifacts.append(
            "definition.md", source
        )  # redacted and size-capped like every byte

    def on_start(identity: ProcessIdentity) -> None:
        nonlocal record
        started = deps.store.transition(
            run_id,
            expected=RunStatus.PENDING,
            then=lambda current: current.start(
                pid=identity.pid,
                pgid=identity.pgid,
                process_start=identity.process_start,
            ),
        )
        if started is None:
            # The tick interrupted the stale PENDING record (secret resolution
            # outran one tick interval). Nothing of ours may be written now.
            if identity.pid != deps.process.own_identity().pid:
                deps.process.signal_group(identity.pgid)
            raise RunLost(run_id)
        record = started

    def current_record() -> RunRecord:
        return record

    try:
        return _run_started(
            chore,
            spec,
            deps,
            ctx,
            current_record=current_record,
            failure=failure,
            secret_values=secret_values,
            credential=credential,
            cwd=cwd,
            artifacts=artifacts,
            started_utc=started_utc,
            on_start=on_start,
        )
    except RunLost:
        note = "lost the start race: the tick closed this run as INTERRUPTED first"
        artifacts.append("errors.log", note + "\n")
        return RunOutcome(deps.store.read_record(run_id), f"{name}: {note}")


def _run_started(
    chore: Chore,
    spec: BackendSpec | None,
    deps: RunDeps,
    ctx: Context,
    *,
    current_record: Callable[[], RunRecord],
    failure: str | None,
    secret_values: Mapping[str, str],
    credential: str | None,
    cwd: str,
    artifacts: Artifacts,
    started_utc: datetime,
    on_start: Callable[[ProcessIdentity], None],
) -> RunOutcome:
    """Everything after the PENDING record exists: start, execute, finish.
    ``current_record`` reads the record ``on_start`` advanced to RUNNING."""
    name = chore.name
    run_id = current_record().run_id

    if failure is not None:
        on_start(deps.process.own_identity())
        artifacts.append("errors.log", failure + "\n")
        execution = _Execution(RunStatus.FAILED, failure, Usage(0, 0, 0.0))
        return RunOutcome(
            _finish(
                current_record(),
                execution,
                chore,
                deps,
                ctx,
                started_utc=started_utc,
                artifacts=artifacts,
            ),
            failure,
        )
    env = _build_env(
        chore, run_id=run_id, secrets=secret_values, inherited=deps.inherited_env
    )
    if chore.kind is Kind.PROMPT:
        assert spec is not None
        on_start(deps.process.own_identity())
        execution = _execute_prompt(
            chore, spec, ctx, credential=credential, artifacts=artifacts
        )
    elif chore.kind is Kind.AGENT:
        assert spec is not None
        execution = _execute_agent(
            chore,
            spec,
            ctx,
            credential=credential,
            env=env,
            cwd=cwd,
            artifacts=artifacts,
            on_start=on_start,
            own_identity=deps.process.own_identity,
        )
    else:
        execution = _execute_command(
            chore, deps, ctx, env=env, cwd=cwd, artifacts=artifacts, on_start=on_start
        )
    final = _finish(
        current_record(),
        execution,
        chore,
        deps,
        ctx,
        started_utc=started_utc,
        artifacts=artifacts,
    )
    return RunOutcome(
        final,
        f"{name}: {final.status.value}" + (f": {final.reason}" if final.reason else ""),
    )
