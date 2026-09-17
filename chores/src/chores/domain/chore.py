"""The Chore definition value and its cross-object bindings
(CHORES.DESIGN.md Subsystem 1, Data Model).

``Chore.from_mapping`` enforces the field-level invariants on an already
parsed mapping (YAML parsing is an adapter). ``check_bindings`` enforces the
invariants that need the backend, the global ceiling and the forbidden
paths: kind matches the backend's port, every ceiling dimension that
applies is declared in the budget, a USD ceiling needs a priced backend,
and ``cwd`` stays clear of this tool's own directories.

No backend *type* (vendor) appears here; a backend is described by the
port it implements and the facts the domain needs about it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from chores.domain.budget import Budget, Ceiling, InvalidBudget
from chores.domain.errors import DomainError
from chores.domain.kinds import KIND_PORT, ExecutionPort, Kind
from chores.domain.run import Billing, RunStatus
from chores.domain.schedule import InvalidSchedule, Schedule

__all__ = [
    "BackendSpec",
    "Chore",
    "ExecutionPort",
    "InvalidChore",
    "Kind",
    "check_bindings",
]

_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_DEFAULT_TIMEOUT_SEC = 600
_DEFAULT_NOTIFY_ON = frozenset(
    {
        RunStatus.FAILED,
        RunStatus.TIMED_OUT,
        RunStatus.BUDGET_EXCEEDED,
        RunStatus.OFFLINE,
        RunStatus.INTERRUPTED,
    }
)
_KNOWN_KEYS = frozenset(
    {
        "name",
        "description",
        "schedule",
        "enabled",
        "kind",
        "backend",
        "model",
        "command",
        "cwd",
        "timeout_sec",
        "budget",
        "ceiling",
        "env",
        "secrets",
        "allowed_tools",
        "defer_on_battery",
        "requires_network",
        "catch_up",
        "notify_on",
    }
)
_BUDGET_KEYS = frozenset({"tokens", "usd", "turns"})


class InvalidChore(DomainError):
    """The definition violates a field-level invariant; the message names the field."""


@dataclass(frozen=True, slots=True)
class BackendSpec:
    """What the domain knows about a configured backend -- never its vendor."""

    name: str
    port: ExecutionPort
    default_model: str | None
    requires_network: bool
    priced: bool
    ceiling: Ceiling
    read_only_tools: frozenset[str]
    priced_models: frozenset[str] = frozenset()
    """The models the price table names; empty when the backend has none
    (``priced`` says whether a table exists at all)."""
    billing: Billing | None = None
    """How this backend charges: METERED spend is only measurable through a
    price table; NONE is free; SUBSCRIPTION reports its own cost. None means
    unknown (a test double)."""


# --- predicates --------------------------------------------------------------


def is_under(path: str, root: str) -> bool:
    """Is ``path`` equal to ``root`` or inside it? Lexical: callers resolve first."""
    return path == root or path.startswith(root.rstrip("/") + "/")


_is_under = is_under


# --- field parsers -----------------------------------------------------------


def _str(
    data: Mapping[str, object], key: str, *, default: str | None = None
) -> str | None:
    value = data.get(key, default)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise InvalidChore(f"{key} must be a non-empty string")
    return value


def _bool(data: Mapping[str, object], key: str, *, default: bool) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise InvalidChore(f"{key} must be true or false")
    return value


def _str_list(data: Mapping[str, object], key: str) -> tuple[str, ...] | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, Sequence) or isinstance(value, str) or not value:
        raise InvalidChore(f"{key} must be a non-empty list of strings")
    if not all(isinstance(item, str) and item for item in value):
        raise InvalidChore(f"{key} must be a non-empty list of strings")
    return tuple(value)


def _str_map(data: Mapping[str, object], key: str) -> Mapping[str, str]:
    value = data.get(key, {})
    if not isinstance(value, Mapping) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in value.items()
    ):
        raise InvalidChore(f"{key} must be a map of string to string")
    return dict(value)


def _budget(data: Mapping[str, object]) -> Budget:
    timeout = data.get("timeout_sec", _DEFAULT_TIMEOUT_SEC)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
        raise InvalidChore("timeout_sec must be a positive integer")
    raw = data.get("budget", {})
    if not isinstance(raw, Mapping):
        raise InvalidChore("budget must be a map")
    unknown = set(raw) - _BUDGET_KEYS
    if unknown:
        raise InvalidChore(f"budget has unknown dimensions: {sorted(unknown)}")
    try:
        return Budget(
            seconds=timeout,
            tokens=_int_or_none(raw, "tokens"),
            usd=_float_or_none(raw, "usd"),
            turns=_int_or_none(raw, "turns"),
        )
    except InvalidBudget as e:
        raise InvalidChore(f"budget: {e}") from e


def _ceiling(data: Mapping[str, object]) -> Ceiling:
    raw = data.get("ceiling", {})
    if not isinstance(raw, Mapping) or set(raw) - _BUDGET_KEYS:
        raise InvalidChore("ceiling must be a map with only tokens, usd, turns")
    try:
        return Ceiling(
            tokens=_int_or_none(raw, "tokens"),
            usd=_float_or_none(raw, "usd"),
            turns=_int_or_none(raw, "turns"),
        )
    except InvalidBudget as e:
        raise InvalidChore(f"ceiling: {e}") from e


def _int_or_none(raw: Mapping[str, object], key: str) -> int | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise InvalidChore(f"{key} must be an integer")
    return value


def _float_or_none(raw: Mapping[str, object], key: str) -> float | None:
    value = raw.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InvalidChore(f"{key} must be a number")
    return float(value)


def _notify_on(data: Mapping[str, object]) -> frozenset[RunStatus]:
    raw = data.get("notify_on")
    if raw is None:
        return _DEFAULT_NOTIFY_ON
    if not isinstance(raw, Sequence) or isinstance(raw, str):
        raise InvalidChore("notify_on must be a list of run statuses")
    statuses: set[RunStatus] = set()
    for item in raw:
        try:
            status = RunStatus(item)
        except ValueError as e:
            raise InvalidChore(f"notify_on: unknown status {item!r}") from e
        if not status.is_run_terminal:
            raise InvalidChore(
                f"notify_on: {status.value} is not a run terminal status"
            )
        statuses.add(status)
    return frozenset(statuses)


# --- the value ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Chore:
    """One definition, validated field by field. Build with :meth:`from_mapping`."""

    name: str
    schedule: Schedule
    kind: Kind
    budget: Budget
    body: str
    description: str | None = None
    enabled: bool = True
    backend: str | None = None
    model: str | None = None
    command: tuple[str, ...] | None = None
    cwd: str | None = None
    ceiling: Ceiling = Ceiling()
    env: Mapping[str, str] | None = None
    secrets: Mapping[str, str] | None = None
    allowed_tools: tuple[str, ...] | None = None
    defer_on_battery: bool = False
    requires_network: bool | None = None
    catch_up: bool = False
    notify_on: frozenset[RunStatus] = _DEFAULT_NOTIFY_ON

    @classmethod
    def from_mapping(cls, data: Mapping[str, object], *, body: str) -> Chore:
        """Validate a parsed front-matter mapping into a Chore or raise InvalidChore."""
        unknown = set(data) - _KNOWN_KEYS
        if unknown:
            raise InvalidChore(f"unknown keys: {sorted(unknown)}")
        name = _str(data, "name")
        if name is None or not _NAME_RE.match(name):
            raise InvalidChore("name must match [a-z0-9]+(-[a-z0-9]+)*")
        schedule_text = _str(data, "schedule")
        if schedule_text is None:
            raise InvalidChore("schedule is required")
        try:
            schedule = Schedule.parse(schedule_text)
        except InvalidSchedule as e:
            raise InvalidChore(f"schedule: {e}") from e
        kind_text = _str(data, "kind")
        try:
            kind = Kind(kind_text)
        except ValueError as e:
            raise InvalidChore("kind must be one of prompt, agent, command") from e
        backend = _str(data, "backend") if "backend" in data else None
        command = _str_list(data, "command")
        allowed_tools = _str_list(data, "allowed_tools")
        if kind is Kind.COMMAND:
            if command is None:
                raise InvalidChore("command kind requires a command argv list")
            if backend is not None or "backend" in data:
                raise InvalidChore("command kind takes no backend")
            if allowed_tools is not None:
                raise InvalidChore("allowed_tools applies to agent kind only")
        else:
            if backend is None:
                raise InvalidChore(f"{kind.value} kind requires a backend")
            if command is not None:
                raise InvalidChore(f"{kind.value} kind takes no command")
            if allowed_tools is not None and kind is not Kind.AGENT:
                raise InvalidChore("allowed_tools applies to agent kind only")
        requires_network = (
            _bool(data, "requires_network", default=False)
            if "requires_network" in data
            else None
        )
        return cls(
            name=name,
            schedule=schedule,
            kind=kind,
            budget=_budget(data),
            body=body,
            description=_str(data, "description"),
            enabled=_bool(data, "enabled", default=True),
            backend=backend,
            model=_str(data, "model"),
            command=command,
            cwd=_str(data, "cwd"),
            ceiling=_ceiling(data),
            env=_str_map(data, "env") or None,
            secrets=_str_map(data, "secrets") or None,
            allowed_tools=allowed_tools,
            defer_on_battery=_bool(data, "defer_on_battery", default=False),
            requires_network=requires_network,
            catch_up=_bool(data, "catch_up", default=False),
            notify_on=_notify_on(data),
        )

    @property
    def port(self) -> ExecutionPort | None:
        return KIND_PORT.get(self.kind)

    def effective_tools(self, backend: BackendSpec) -> frozenset[str]:
        """Tool allowlist: the declared list, else the adapter's read-only set."""
        if self.allowed_tools is not None:
            return frozenset(self.allowed_tools)
        return backend.read_only_tools

    def needs_network(self, backend: BackendSpec | None) -> bool:
        if self.requires_network is not None:
            return self.requires_network
        return backend.requires_network if backend else False


# --- bindings ----------------------------------------------------------------


def check_bindings(
    chore: Chore,
    *,
    backend: BackendSpec | None,
    global_ceiling: Ceiling,
    forbidden_paths: Sequence[str],
) -> list[str]:
    """Violations that need more than the definition itself. Empty means valid."""
    out: list[str] = []
    if chore.kind is not Kind.COMMAND:
        if backend is None:
            out.append(f"backend {chore.backend!r} is not configured")
        elif backend.port is not chore.port:
            wanted = chore.port.value if chore.port else "?"
            out.append(
                f"kind {chore.kind.value} needs a {wanted} port but backend "
                f"{backend.name!r} implements {backend.port.value}"
            )
        usd_applies = (
            chore.budget.usd is not None
            or chore.ceiling.usd is not None
            or global_ceiling.usd is not None
            or (backend is not None and backend.ceiling.usd is not None)
        )
        if backend is not None and not backend.priced:
            if backend.ceiling.usd is not None:
                out.append(
                    f"backend {backend.name!r} has a usd ceiling but no price table"
                )
            elif backend.billing is Billing.METERED and usd_applies:
                out.append(
                    f"backend {backend.name!r} is metered but has no price table: "
                    "a usd budget or ceiling would count its spend as zero"
                )
        if backend is not None and not (chore.model or backend.default_model):
            out.append(
                f"no model: set model on the chore or on backend {backend.name!r}"
            )
        if backend is not None and backend.priced_models:
            model = chore.model or backend.default_model
            if usd_applies and model and model not in backend.priced_models:
                out.append(
                    f"model {model!r} has no price on backend {backend.name!r}: "
                    "a usd budget or ceiling would count its spend as zero"
                )
        if chore.kind is Kind.AGENT and chore.budget.turns is None:
            out.append("agent kind requires budget.turns (the in-run bound)")
        applicable = set(chore.ceiling.dimensions()) | set(global_ceiling.dimensions())
        if backend is not None:
            applicable |= set(backend.ceiling.dimensions())
        if chore.kind is not Kind.AGENT:
            applicable.discard("turns")  # only agent runs have turns
        missing = sorted(applicable - set(chore.budget.declared_dimensions()))
        if missing:
            out.append(
                f"budget must declare {missing}: a ceiling applies in those dimensions"
            )
    if chore.cwd is not None:
        for root in forbidden_paths:
            if _is_under(chore.cwd, root) or _is_under(root, chore.cwd):
                out.append(f"cwd {chore.cwd!r} may not be inside or contain {root!r}")
    return out
