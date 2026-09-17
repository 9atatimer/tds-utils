"""ProcessPort -- how a command (or an agent CLI) is confined and bounded
(CHORES.DESIGN.md Subsystem 3, "Process bound")."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from chores.ports.agent import ProcessIdentity


@dataclass(frozen=True, slots=True)
class ProcessRequest:
    argv: Sequence[str]
    cwd: str
    env: Mapping[str, str]
    timeout_sec: int
    kill_grace_sec: int
    stdin_text: str | None = None
    max_output_bytes: int | None = None
    """Per-stream cap on captured stdout/stderr; the rest is drained and
    dropped (``ProcessResult.output_truncated``), never buffered."""


@dataclass(frozen=True, slots=True)
class ProcessResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    cpu_seconds: float
    seconds: float
    output_truncated: bool = False


class RunningProcess(Protocol):
    @property
    def identity(self) -> ProcessIdentity: ...

    def wait(self) -> ProcessResult:
        """Block until exit or timeout; on timeout the whole group is killed."""
        ...

    def terminate_group(self) -> None: ...


class ProcessPort(Protocol):
    def spawn(self, request: ProcessRequest) -> RunningProcess:
        """Start the child in its own session or raise ProcessError."""
        ...

    def alive(self, pid: int, *, process_start: float) -> bool:
        """Is that exact process (pid + start time) still running?"""
        ...

    def signal_group(self, pgid: int) -> bool:
        """SIGTERM a process group; True if it existed."""
        ...

    def own_identity(self) -> ProcessIdentity:
        """This process, for runs that execute in-process (prompt runs)."""
        ...
