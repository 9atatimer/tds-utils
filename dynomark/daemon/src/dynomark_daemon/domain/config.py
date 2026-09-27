"""The daemon's settings, loaded once by the composition root."""

from dataclasses import dataclass
from pathlib import PurePath

from dynomark_daemon.domain.ids import HostId
from dynomark_daemon.domain.job import RetryPolicy
from dynomark_daemon.domain.roles import HostRole
from dynomark_daemon.domain.tree import OwnedRoots


@dataclass(frozen=True, slots=True)
class ModelInfo:
    """A model id supplied at the edge, and whether it runs locally."""

    model_id: str
    local: bool


@dataclass(frozen=True, slots=True)
class Config:
    """``HostRole``, model ids, store path, ``RetryPolicy``, rebuild cadence."""

    host_id: HostId
    role: HostRole
    owned_roots: OwnedRoots
    embedding_model: ModelInfo
    completion_model: ModelInfo
    store_path: PurePath
    retry: RetryPolicy
    rebuild_cadence_ms: int | None = None
