"""AgentPort -- the agentic seam (CHORES.DESIGN.md Subsystem 4)."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from chores.domain.run import Billing


@dataclass(frozen=True, slots=True)
class AgentTask:
    body: str
    model: str
    cwd: str
    allowed_tools: frozenset[str]
    max_turns: int | None
    timeout_sec: int
    env: Mapping[str, str]
    kill_grace_sec: int = 10


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    pid: int
    pgid: int
    process_start: float


@dataclass(frozen=True, slots=True)
class AgentResult:
    text: str
    events: Sequence[Mapping[str, object]]
    tokens_in: int
    tokens_out: int
    usd: float | None
    turns: int | None
    billing: Billing
    exit_code: int
    timed_out: bool
    cpu_seconds: float


class AgentPort(Protocol):
    def run(
        self, task: AgentTask, *, on_start: Callable[[ProcessIdentity], None]
    ) -> AgentResult:
        """Run the task to completion; call ``on_start`` once the process exists."""
        ...
