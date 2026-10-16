"""The daemon's settings, loaded once by the composition root, and the rule
that marks a model local (Security Considerations, "Cloud model egress";
issue #411)."""

from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import PurePath
from typing import Final

from dynomark_daemon.domain.ids import HostId
from dynomark_daemon.domain.job import RetryPolicy
from dynomark_daemon.domain.roles import HostRole
from dynomark_daemon.domain.tree import OwnedRoots

LOOPBACK_NAMES: Final = frozenset({"localhost"})
"""Host names that are loopback by definition; any loopback address is too."""
CLOUD_TAG: Final = "cloud"
"""What an Ollama cloud model's tag contains (``:cloud``, ``:120b-cloud``)."""


# --- Predicates ---


def is_loopback_host(host: str) -> bool:
    """``host`` names this machine: ``localhost`` or a loopback address."""
    if host.lower() in LOOPBACK_NAMES:
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def is_cloud_tagged(model: str) -> bool:
    """The model id's tag (after its last ``:``) marks an Ollama cloud model:
    the local server forwards it to the vendor's cloud."""
    _, colon, tag = model.rpartition(":")
    return bool(colon) and CLOUD_TAG in tag.lower()


def is_local_model(host: str, model: str, *, declared_remote: bool) -> bool:
    """The model runs on this machine, so what it is sent stays here: the
    model server's host is loopback, the id carries no cloud tag, and the
    config does not declare the endpoint remote (a tunnel or proxy that
    listens on loopback)."""
    return not declared_remote and is_loopback_host(host) and not is_cloud_tagged(model)


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
