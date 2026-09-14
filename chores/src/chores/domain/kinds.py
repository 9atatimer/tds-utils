"""Chore kinds and the execution port each selects (CHORES.DESIGN.md Subsystem 1)."""

from __future__ import annotations

from enum import Enum


class Kind(Enum):
    PROMPT = "prompt"
    AGENT = "agent"
    COMMAND = "command"


class ExecutionPort(Enum):
    """Which seam a backend implements. ``kind`` selects the port."""

    COMPLETION = "completion"
    AGENT = "agent"


KIND_PORT = {Kind.PROMPT: ExecutionPort.COMPLETION, Kind.AGENT: ExecutionPort.AGENT}
