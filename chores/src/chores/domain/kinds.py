"""Chore kinds and the execution port each selects (CHORES.DESIGN.md Subsystem 1)."""

from __future__ import annotations

from enum import Enum


class Kind(Enum):
    PROMPT = "prompt"
    AGENT = "agent"
    COMMAND = "command"
    UNKNOWN = "unknown"
    """Only on an INVALID record whose definition never parsed far enough
    to say; never a valid chore's kind (from_mapping refuses it)."""


DEFINABLE_KINDS = frozenset({Kind.PROMPT, Kind.AGENT, Kind.COMMAND})


class ExecutionPort(Enum):
    """Which seam a backend implements. ``kind`` selects the port."""

    COMPLETION = "completion"
    AGENT = "agent"


KIND_PORT = {Kind.PROMPT: ExecutionPort.COMPLETION, Kind.AGENT: ExecutionPort.AGENT}
