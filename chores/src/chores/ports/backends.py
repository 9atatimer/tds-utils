"""Backend configuration (edge values) and the catalog seam.

``BackendConfig`` is what ``backends.yaml`` says: a vendor ``type`` and the
volatile values that type needs (URL, header, credential reference, prices).
It is edge data, so it lives here, not in the domain. The catalog turns a
config into the domain's ``BackendSpec`` plus a port implementation; the
registry behind it is the single place that knows the vendor set.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from chores.domain.budget import Ceiling
from chores.domain.chore import BackendSpec
from chores.ports.agent import AgentPort
from chores.ports.completion import CompletionPort


@dataclass(frozen=True, slots=True)
class Price:
    """USD per one million tokens, in and out. Both rates are finite and
    non-negative: a NaN rate defeats every ceiling comparison and a negative
    one subtracts spend, so neither may enter from backends.yaml."""

    in_per_1m: float
    out_per_1m: float

    def __post_init__(self) -> None:
        for name in ("in_per_1m", "out_per_1m"):
            rate = getattr(self, name)
            if not math.isfinite(rate) or rate < 0:
                raise ValueError(f"price {name} must be finite and >= 0 (got {rate})")


@dataclass(frozen=True, slots=True)
class BackendConfig:
    name: str
    type: str
    model: str | None = None
    base_url: str | None = None
    auth_header: str | None = None
    credential_ref: str | None = None
    prices: Mapping[str, Price] = field(default_factory=dict)
    ceiling: Ceiling = Ceiling()
    requires_network: bool | None = None
    extra: Mapping[str, object] = field(default_factory=dict)


class BackendCatalogPort(Protocol):
    @property
    def errors(self) -> Sequence[str]:
        """Configuration problems found while building the catalog."""
        ...

    def spec(self, name: str) -> BackendSpec | None: ...

    def credential_ref(self, name: str) -> str | None:
        """The credential reference this backend needs, resolved by the runner."""
        ...

    def completion(
        self, name: str, *, credential: str | None = None
    ) -> CompletionPort: ...

    def agent(self, name: str, *, credential: str | None = None) -> AgentPort: ...

    def probe_url(self, name: str) -> str | None:
        """The URL the network probe should try for this backend, if any."""
        ...
