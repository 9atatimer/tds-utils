"""A connection's standing: the contract version each side speaks and what
that lets continue (DYNOMARK.DESIGN.md, Transport contract, "Identity and
version"; contract/v2 README, Connection lifecycle)."""

from enum import StrEnum
from typing import Final

from dynomark_daemon.domain.ids import ProfileId
from dynomark_daemon.domain.roles import HostRole

DAEMON_CONTRACT_VERSION: Final = 2
"""The transport contract version this daemon speaks (contract/v2)."""


class HelloMode(StrEnum):
    """What a connection may do after the handshake."""

    FULL = "full"
    READ_ONLY = "read_only"
    REFUSED = "refused"


def negotiate(extension: int, daemon: int) -> HelloMode:
    """Equal versions: everything continues. A newer extension: only search and
    chat (the read-only set), spoken at the daemon's version. An older one:
    nothing but the handshake."""
    if extension == daemon:
        return HelloMode.FULL
    return HelloMode.READ_ONLY if extension > daemon else HelloMode.REFUSED


class WriterBinding(StrEnum):
    """Which profile a writer daemon files for, as one profile sees it (Key
    Decisions "Writer binding" 2026-10-16, issue #419)."""

    THIS_PROFILE = "this_profile"
    OTHER_PROFILE = "other_profile"
    UNBOUND = "unbound"


def writer_binding(
    configured: HostRole, writer_profile: ProfileId | None, profile: ProfileId
) -> WriterBinding | None:
    """The binding ``profile`` sees on a writer daemon; ``None`` on a reader,
    which binds no profile."""
    if configured is not HostRole.WRITER:
        return None
    if writer_profile is None:
        return WriterBinding.UNBOUND
    if writer_profile == profile:
        return WriterBinding.THIS_PROFILE
    return WriterBinding.OTHER_PROFILE


def served_role(
    configured: HostRole, writer_profile: ProfileId | None, profile: ProfileId
) -> HostRole:
    """A writer daemon files for one profile, the one its store is bound to,
    and serves every other profile as a reader (Goal 7)."""
    if configured is HostRole.WRITER and writer_profile == profile:
        return HostRole.WRITER
    return HostRole.READER
