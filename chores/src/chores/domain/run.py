"""Run statuses (CHORES.DESIGN.md State Machine). The record and its
transitions arrive with task-004; the enum is needed by definitions first."""

from __future__ import annotations

from enum import Enum


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
