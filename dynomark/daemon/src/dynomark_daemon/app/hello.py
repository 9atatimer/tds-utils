"""Use cases: the handshake and the daemon's status (DYNOMARK.DESIGN.md,
Transport contract, "Identity and version"; Goal 7; contract/v1 README,
Connection lifecycle and the ``status`` message).
"""

from dataclasses import dataclass

from dynomark_daemon.domain.config import Config, ModelInfo
from dynomark_daemon.domain.connection import (
    DAEMON_CONTRACT_VERSION,
    HelloMode,
    negotiate,
    served_role,
)
from dynomark_daemon.domain.ids import HostId, ProfileId
from dynomark_daemon.domain.job import JobState
from dynomark_daemon.domain.roles import HostRole
from dynomark_daemon.domain.tree import FolderPath, OwnedRoots
from dynomark_daemon.ports.store import CorpusStorePort

_IN_FLIGHT = (JobState.QUEUED, JobState.CAPTURING, JobState.ENRICHED, JobState.PLACED)


@dataclass(frozen=True, slots=True)
class Greeting:
    """The daemon's half of the handshake for one connection."""

    host_id: HostId
    role: HostRole
    mode: HelloMode
    owned_roots: OwnedRoots
    version: int


@dataclass(frozen=True, slots=True)
class DaemonStatus:
    """What the settings page shows, including whether each model is local."""

    role: HostRole
    host_id: HostId
    contract_version: int
    embedding: ModelInfo
    completion: ModelInfo
    queue_depth: int


def owned_roots_for(
    profile_id: ProfileId, config: Config, *, store: CorpusStorePort
) -> OwnedRoots:
    """``Config``'s owned roots with the ``Follow Up`` this profile resolved."""
    follow_up = store.follow_up_of(profile_id) or config.owned_roots.follow_up
    return OwnedRoots(
        follow_up=follow_up,
        dynomark=config.owned_roots.dynomark,
        graveyard=config.owned_roots.graveyard,
    )


def hello(
    profile_id: ProfileId,
    version: int,
    follow_up: FolderPath,
    config: Config,
    *,
    store: CorpusStorePort,
) -> Greeting:
    """Answer an extension's ``hello``: the mode its version allows, and the
    role its profile is served with. The first profile to complete a full
    hello on a writer daemon binds the store."""
    mode = negotiate(version, DAEMON_CONTRACT_VERSION)
    if mode is HelloMode.FULL and config.role is HostRole.WRITER:
        store.bind_writer_profile(profile_id)
    store.put_follow_up(profile_id, follow_up)
    return Greeting(
        host_id=config.host_id,
        role=served_role(config.role, store.writer_profile(), profile_id),
        mode=mode,
        owned_roots=owned_roots_for(profile_id, config, store=store),
        version=DAEMON_CONTRACT_VERSION,
    )


def status(role: HostRole, config: Config, *, store: CorpusStorePort) -> DaemonStatus:
    """The daemon's status as a connection served ``role`` sees it."""
    in_flight = sum(len(store.list_jobs(state=state)) for state in _IN_FLIGHT)
    return DaemonStatus(
        role=role,
        host_id=config.host_id,
        contract_version=DAEMON_CONTRACT_VERSION,
        embedding=config.embedding_model,
        completion=config.completion_model,
        queue_depth=in_flight,
    )
