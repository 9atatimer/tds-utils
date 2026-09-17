"""The run use case (CHORES.DESIGN.md Subsystem 3): admit, resolve, execute,
record. The only path that starts a run, so admission lives here as well
as in tick. Orchestrates ports only; every decision is a domain policy.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from chores.application.context import (
    Context,
    Host,
    admit,
    binding_errors,
    find_chore,
    invalid_record_name,
    load_context,
    mint_run_id,
    post,
    write_outcome,
)
from chores.application.paths import Paths
from chores.domain.budget import Budget, SpendAction, Usage, spend_policy
from chores.domain.chore import BackendSpec, Chore
from chores.domain.kinds import Kind
from chores.domain.policies import Decision, circuit_breaker, redact
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
from chores.ports.store import Artifact, RunStorePort, WorkspacesPort

_INHERITED_KEYS = ("PATH", "HOME", "LANG")


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


@dataclass(frozen=True, slots=True)
class RunOutcome:
    record: RunRecord | None
    message: str
    plan: RunPlan | None = None


@dataclass
class _Artifacts:
    """Every byte the run writes goes through here: redaction, then the size cap."""

    store: RunStorePort
    run_id: str
    secrets: Sequence[str]
    max_bytes: int
    truncated: bool = False

    def append(self, name: Artifact, text: str) -> None:
        if self.truncated:
            return
        clean = redact(text, self.secrets)
        if (
            self.store.run_dir_bytes(self.run_id) + len(clean.encode("utf-8"))
            > self.max_bytes
        ):
            self.truncated = True
            return
        self.store.append_artifact(self.run_id, name, clean)

    def event(self, payload: Mapping[str, object]) -> None:
        self.append("transcript.jsonl", json.dumps(dict(payload)) + "\n")


@dataclass
class _Execution:
    status: RunStatus
    reason: str | None
    usage: Usage
    backend: str | None = None
    model: str | None = None
    billing: Billing | None = None
    exit_code: int | None = None


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


def ctx_store_kill_requested(artifacts: _Artifacts) -> bool:
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
    artifacts: _Artifacts,
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
    artifacts: _Artifacts,
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
    if result.timed_out:
        return _Execution(
            RunStatus.TIMED_OUT,
            f"timed out after {chore.budget.seconds}s",
            usage,
            backend=spec.name,
            model=model,
            billing=result.billing,
            exit_code=result.exit_code,
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
        )
    return _Execution(
        RunStatus.SUCCEEDED,
        None,
        usage,
        backend=spec.name,
        model=model,
        billing=result.billing,
        exit_code=0,
    )


def _execute_command(
    chore: Chore,
    deps: RunDeps,
    ctx: Context,
    *,
    env: Mapping[str, str],
    cwd: str,
    artifacts: _Artifacts,
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
    if result.timed_out:
        return _Execution(
            RunStatus.TIMED_OUT,
            f"timed out after {chore.budget.seconds}s",
            usage,
            exit_code=result.exit_code,
        )
    if deps.store.kill_requested(artifacts.run_id):
        return _Execution(
            RunStatus.KILLED, "killed by chores kill", usage, exit_code=result.exit_code
        )
    if result.exit_code != 0:
        tail = result.stderr.strip()[-200:]
        return _Execution(
            RunStatus.FAILED,
            f"exit {result.exit_code}: {tail}".rstrip(": "),
            usage,
            exit_code=result.exit_code,
        )
    return _Execution(RunStatus.SUCCEEDED, None, usage, exit_code=0)


def _finish(
    record: RunRecord,
    execution: _Execution,
    chore: Chore,
    deps: RunDeps,
    ctx: Context,
    *,
    started_utc: datetime,
    artifacts: _Artifacts,
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
    if artifacts.truncated:
        record = record.truncate()
    record = record.finish(status, ended=ended, reason=reason)
    deps.store.write_record(record)
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
    _apply_breaker(chore, deps, ctx, at=ended)
    return record


def _apply_breaker(chore: Chore, deps: RunDeps, ctx: Context, *, at: datetime) -> None:
    recent = [
        r.status
        for r in reversed(deps.store.records(chore=chore.name))
        if r.status.is_run_terminal
    ]
    verdict = circuit_breaker(
        recent, threshold=ctx.definitions.config.failure_threshold
    )
    if (
        verdict.decision is Decision.PAUSE
        and deps.store.chore_paused(chore.name) is None
    ):
        reason = verdict.reason or "breaker"
        deps.store.pause_chore(chore.name, reason)
        post(
            deps.store,
            deps.notifier,
            at=at,
            level="alert",
            text=(
                f"{chore.name} paused by breaker: {reason}; "
                f"`chores resume {chore.name}` to clear"
            ),
            chore=chore.name,
        )


# --- the use case ------------------------------------------------------------


def run_chore(
    name: str, deps: RunDeps, *, force: bool = False, dry_run: bool = False
) -> RunOutcome:
    ctx = load_context(deps.definitions, deps.catalog_for)
    host = Host(deps.store, deps.process, deps.clock, deps.power, deps.network)
    found = find_chore(ctx.definitions, name)
    kind = found.kind if isinstance(found, Chore) else Kind.COMMAND
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
    verdict, spec = admit(ctx, chore, host, force=force)
    cwd = (
        _cwd(chore, deps) if not dry_run or chore.cwd else (chore.cwd or "<workspace>")
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
                    chore, run_id="<run-id>", secrets={}, inherited=deps.inherited_env
                )
            ),
            secret_names=sorted(chore.secrets or {}),
            argv=chore.command,
            budget=chore.budget,
            admission=verdict.decision.name
            if verdict.decision is Decision.ADMIT
            else "SKIP",
            admission_reason=verdict.reason,
        )
        return RunOutcome(None, "dry run", plan)
    run_id = mint_run_id(name, deps.clock, deps.run_id_suffix)
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
        )
        return RunOutcome(
            record, f"{name}: {verdict.record_status.value}: {verdict.reason}"
        )

    started_utc = deps.clock.now_utc()
    record = RunRecord.pending(
        run_id=run_id,
        chore=name,
        kind=chore.kind,
        definition_rev=ctx.definitions.revision,
        started=started_utc,
    )
    deps.store.write_record(record)

    secret_values, credential, failure = _resolve_secrets(chore, ctx, deps)
    redaction = [*secret_values.values(), *([credential] if credential else [])]
    artifacts = _Artifacts(
        deps.store, run_id, redaction, ctx.definitions.config.max_run_dir_bytes
    )
    source = deps.definitions.source(name)
    if source is not None:
        artifacts.append(
            "definition.md", source
        )  # redacted and size-capped like every byte

    def on_start(identity: ProcessIdentity) -> None:
        nonlocal record
        record = record.start(
            pid=identity.pid, pgid=identity.pgid, process_start=identity.process_start
        )
        deps.store.write_record(record)

    if failure is not None:
        on_start(deps.process.own_identity())
        artifacts.append("errors.log", failure + "\n")
        execution = _Execution(RunStatus.FAILED, failure, Usage(0, 0, 0.0))
        return RunOutcome(
            _finish(
                record,
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
        record,
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
