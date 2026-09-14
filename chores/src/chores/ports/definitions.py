"""DefinitionsPort -- reading $CHORES_HOME (CHORES.DESIGN.md Subsystem 1)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from chores.domain.budget import Ceiling
from chores.domain.chore import Chore
from chores.ports.backends import BackendConfig


@dataclass(frozen=True, slots=True)
class GlobalConfig:
    """``config.yaml``; every field has the design's default."""

    ceiling: Ceiling = Ceiling()
    tick_interval_sec: int = 60
    missed_grace_sec: int = 120
    failure_threshold: int = 3
    retention_days: int = 90
    count_subscription_usd: bool = False
    secret_timeout_sec: int = 30
    kill_grace_sec: int = 10
    max_run_dir_bytes: int = 50 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class InvalidDefinition:
    name: str
    error: str


@dataclass(frozen=True, slots=True)
class Definitions:
    chores: Sequence[Chore]
    invalid: Sequence[InvalidDefinition]
    backends: Mapping[str, BackendConfig]
    config: GlobalConfig
    revision: str
    errors: Sequence[str] = field(default_factory=tuple)


class DefinitionsPort(Protocol):
    def load(self) -> Definitions: ...

    def source(self, name: str) -> str | None:
        """The raw definition file for ``name`` (front-matter and body)."""
        ...
