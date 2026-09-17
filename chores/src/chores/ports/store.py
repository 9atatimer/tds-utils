"""RunStorePort -- run persistence (CHORES.DESIGN.md Subsystems 3, 7, 8, Data
Model). One port because the state directory is one thing: records, run
artifacts, the ledger, the notification queue, the pause sentries, the tick
liveness file and the tick lock live and die together.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from chores.domain.run import RunRecord, RunStatus

# One of: definition.md, transcript.jsonl, stdout.log, stderr.log, errors.log
Artifact = str


@dataclass(frozen=True, slots=True)
class Notification:
    id: str
    ts: datetime
    run_id: str | None
    chore: str | None
    level: str
    text: str
    read: bool


@dataclass(frozen=True, slots=True)
class TickMark:
    at: datetime
    ledger_rows: int


class RunStorePort(Protocol):
    # --- records ---
    def write_record(self, record: RunRecord) -> None: ...

    def read_record(self, run_id: str) -> RunRecord | None: ...

    def transition(
        self,
        run_id: str,
        *,
        expected: RunStatus,
        then: Callable[[RunRecord], RunRecord],
    ) -> RunRecord | None:
        """Check-and-set: atomically against ``write_record``, if the stored
        record's status is ``expected`` replace it with ``then(current)`` and
        return that; otherwise write nothing and return None."""
        ...

    def records(
        self, *, chore: str | None = None, since: datetime | None = None
    ) -> Sequence[RunRecord]:
        """Records newest first, filtered by chore and by ``started >= since``."""
        ...

    # --- artifacts ---
    def append_artifact(self, run_id: str, name: Artifact, text: str) -> int:
        """Append and return the run directory's size in bytes afterwards."""
        ...

    def read_artifact(self, run_id: str, name: Artifact) -> str: ...

    def run_dir_bytes(self, run_id: str) -> int: ...

    # --- ledger ---
    def append_ledger(self, row: Mapping[str, object]) -> None: ...

    def ledger_rows(
        self, *, since: datetime | None = None
    ) -> Sequence[Mapping[str, object]]: ...

    def ledger_count(self) -> int: ...

    # --- notifications ---
    def notify(
        self,
        *,
        at: datetime,
        level: str,
        text: str,
        run_id: str | None = None,
        chore: str | None = None,
    ) -> Notification: ...

    def notifications(self, *, unread_only: bool = True) -> Sequence[Notification]: ...

    def dismiss(self, notification_id: str) -> bool: ...

    # --- pause sentries ---
    def pause(self, reason: str) -> None: ...

    def unpause(self) -> None: ...

    def paused(self) -> str | None: ...

    def pause_chore(self, name: str, reason: str) -> None: ...

    def resume_chore(self, name: str) -> None: ...

    def chore_paused(self, name: str) -> str | None: ...

    # --- tick liveness and exclusion ---
    def mark_tick(self, mark: TickMark) -> None: ...

    def last_tick(self) -> TickMark | None: ...

    def tick_lock(self) -> AbstractContextManager[bool]:
        """Enter True when the lock was acquired, False when another tick holds it."""
        ...

    def artifacts(self, run_id: str) -> Iterator[Artifact]: ...

    def delete_run(self, run_id: str) -> bool:
        """Remove a run directory (retention); the ledger is never touched."""
        ...

    # --- kill requests (chores kill writes, the runner reads) ---
    def request_kill(self, run_id: str) -> None: ...

    def kill_requested(self, run_id: str) -> bool: ...


class WorkspacesPort(Protocol):
    def ensure(self, chore: str) -> str:
        """The default cwd for a chore, created if absent; returns its path."""
        ...
