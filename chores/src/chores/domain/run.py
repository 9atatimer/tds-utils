"""Run records, their state machine and the ledger row (CHORES.DESIGN.md
State Machine, Data Model).

A record is an immutable value; every transition returns a new one and an
illegal transition raises. Tick-written outcomes (MISSED, INVALID, SKIPPED_*,
DEFERRED_BATTERY) are terminal on creation.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum

from chores.domain.budget import Usage
from chores.domain.errors import DomainError
from chores.domain.kinds import Kind

LEDGER_SCHEMA = "chores/v1"


class RunStatus(Enum):
    """Every status a run record can carry, run-lifecycle and tick-written alike."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    KILLED = "KILLED"
    OFFLINE = "OFFLINE"
    INTERRUPTED = "INTERRUPTED"
    MISSED = "MISSED"
    INVALID = "INVALID"
    SKIPPED_OVERLAP = "SKIPPED_OVERLAP"
    SKIPPED_PAUSED = "SKIPPED_PAUSED"
    SKIPPED_CEILING = "SKIPPED_CEILING"
    SKIPPED_OFFLINE = "SKIPPED_OFFLINE"
    DEFERRED_BATTERY = "DEFERRED_BATTERY"

    @property
    def is_run_terminal(self) -> bool:
        """A terminal status of a run that actually started (runner-written)."""
        return self in _RUN_TERMINAL

    @property
    def is_terminal(self) -> bool:
        return self is not RunStatus.PENDING and self is not RunStatus.RUNNING

    @property
    def is_failure(self) -> bool:
        """Counts toward the circuit breaker."""
        return self in _FAILURES


_RUN_TERMINAL = frozenset(
    {
        RunStatus.SUCCEEDED,
        RunStatus.FAILED,
        RunStatus.TIMED_OUT,
        RunStatus.BUDGET_EXCEEDED,
        RunStatus.KILLED,
        RunStatus.OFFLINE,
        RunStatus.INTERRUPTED,
    }
)
_FAILURES = frozenset(
    {
        RunStatus.FAILED,
        RunStatus.TIMED_OUT,
        RunStatus.BUDGET_EXCEEDED,
        RunStatus.INTERRUPTED,
    }
)


class Billing(Enum):
    METERED = "metered"
    SUBSCRIPTION = "subscription"
    NONE = "none"


class IllegalTransition(DomainError):
    """The state machine forbids this transition."""


# --- helpers -----------------------------------------------------------------


def new_run_id(chore: str, *, at: datetime, suffix: str) -> str:
    """``<chore>-<UTC yyyymmddThhmmssZ>-<suffix>``; ``at`` is UTC."""
    return f"{chore}-{at.strftime('%Y%m%dT%H%M%SZ')}-{suffix}"


# --- the record --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunRecord:
    """One run (or one tick-written outcome) of one chore."""

    run_id: str
    chore: str
    kind: Kind
    definition_rev: str
    status: RunStatus
    started: datetime
    reason: str | None = None
    ended: datetime | None = None
    pid: int | None = None
    pgid: int | None = None
    process_start: float | None = None
    backend: str | None = None
    model: str | None = None
    billing: Billing | None = None
    usage: Usage | None = None
    exit_code: int | None = None
    truncated: bool = False

    @classmethod
    def pending(
        cls,
        *,
        run_id: str,
        chore: str,
        kind: Kind,
        definition_rev: str,
        started: datetime,
    ) -> RunRecord:
        return cls(
            run_id=run_id,
            chore=chore,
            kind=kind,
            definition_rev=definition_rev,
            status=RunStatus.PENDING,
            started=started,
        )

    @classmethod
    def outcome(
        cls,
        *,
        run_id: str,
        chore: str,
        kind: Kind,
        definition_rev: str,
        status: RunStatus,
        reason: str,
        at: datetime,
    ) -> RunRecord:
        """A tick-written outcome: terminal on creation."""
        if status in _RUN_TERMINAL or not status.is_terminal:
            raise IllegalTransition(f"{status.value} is not a tick-written outcome")
        return cls(
            run_id=run_id,
            chore=chore,
            kind=kind,
            definition_rev=definition_rev,
            status=status,
            started=at,
            ended=at,
            reason=reason,
        )

    def start(self, *, pid: int, pgid: int, process_start: float) -> RunRecord:
        if self.status is not RunStatus.PENDING:
            raise IllegalTransition(f"cannot start from {self.status.value}")
        return replace(
            self,
            status=RunStatus.RUNNING,
            pid=pid,
            pgid=pgid,
            process_start=process_start,
        )

    def with_usage(
        self,
        usage: Usage,
        *,
        backend: str | None = None,
        model: str | None = None,
        billing: Billing | None = None,
        exit_code: int | None = None,
    ) -> RunRecord:
        if self.status is not RunStatus.RUNNING:
            raise IllegalTransition(
                f"usage is recorded while RUNNING, not {self.status.value}"
            )
        return replace(
            self,
            usage=usage,
            backend=backend if backend is not None else self.backend,
            model=model if model is not None else self.model,
            billing=billing if billing is not None else self.billing,
            exit_code=exit_code if exit_code is not None else self.exit_code,
        )

    def finish(
        self, status: RunStatus, *, ended: datetime, reason: str | None
    ) -> RunRecord:
        if status not in _RUN_TERMINAL:
            raise IllegalTransition(f"{status.value} is not a run terminal status")
        if self.status is RunStatus.PENDING and status is not RunStatus.INTERRUPTED:
            raise IllegalTransition("a PENDING run can only become INTERRUPTED")
        if self.status.is_terminal:
            raise IllegalTransition(f"{self.status.value} is final")
        if status is not RunStatus.SUCCEEDED and not reason:
            raise IllegalTransition(f"{status.value} requires a reason")
        return replace(
            self,
            status=status,
            ended=ended,
            reason=reason,
            pid=None,
            pgid=None,
            process_start=None,
        )

    def truncate(self) -> RunRecord:
        return replace(self, truncated=True)


def to_ledger_row(record: RunRecord) -> dict[str, str | int | float | bool | None]:
    """Flatten a terminal record into one ledger row (no prompt content)."""
    usage = record.usage
    return {
        "schema": LEDGER_SCHEMA,
        "run_id": record.run_id,
        "chore": record.chore,
        "kind": record.kind.value,
        "definition_rev": record.definition_rev,
        "status": record.status.value,
        "reason": record.reason,
        "started": record.started.isoformat(),
        "ended": record.ended.isoformat() if record.ended else None,
        "backend": record.backend,
        "model": record.model,
        "billing": record.billing.value if record.billing else None,
        "tokens_in": usage.tokens_in if usage else 0,
        "tokens_out": usage.tokens_out if usage else 0,
        "usd": usage.usd if usage else None,
        "turns": usage.turns if usage else None,
        "seconds": usage.seconds if usage else 0.0,
        "cpu_seconds": usage.cpu_seconds if usage else 0.0,
        "disk_bytes": usage.disk_bytes if usage else 0,
        "exit_code": record.exit_code,
        "truncated": record.truncated,
    }
