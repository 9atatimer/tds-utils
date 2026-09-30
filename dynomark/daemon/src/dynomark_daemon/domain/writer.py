"""The writer marker (DYNOMARK.DESIGN.md, Key Decisions "Two writers", MVP
half; Non-Goals: two writers are never arbitrated automatically; contract/v1
README, Writer marker).

A writer keeps an empty folder titled ``dynomark-writer:<host_id>`` directly
in ``Dynomark``. A host configured ``writer`` that sees another host's
marker is in conflict and refuses every write-producing use case; clearing
a stale marker is a user edit in the tree.
"""

import re
from dataclasses import dataclass
from typing import Final

from dynomark_daemon.domain.batch import OpCreateFolder, Operation
from dynomark_daemon.domain.ids import HostId
from dynomark_daemon.domain.roles import HostRole
from dynomark_daemon.domain.tree import (
    WRITER_MARKER_PREFIX,
    NodeKind,
    OwnedRoots,
    Snapshot,
)

HOST_ID: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
"""A ``HostId`` (contract v1)."""
MAX_OTHER_WRITERS: Final = 64
"""``writer.status.result`` names at most this many other writers."""


def marker_title(host_id: HostId) -> str:
    return f"{WRITER_MARKER_PREFIX}{host_id}"


def markers_in(snapshot: Snapshot, roots: OwnedRoots) -> tuple[HostId, ...]:
    """The host ids whose marker folders sit directly in ``Dynomark``, in tree
    order, each once; a marker title whose suffix is no host id is ignored."""
    dynomark = snapshot.resolve(roots.dynomark)
    if dynomark is None:
        return ()
    hosts: list[HostId] = []
    for child in snapshot.children(dynomark):
        suffix = child.title.removeprefix(WRITER_MARKER_PREFIX)
        if (
            child.kind is NodeKind.FOLDER
            and child.title.startswith(WRITER_MARKER_PREFIX)
            and HOST_ID.fullmatch(suffix)
            and suffix not in hosts
        ):
            hosts.append(HostId(suffix))
    return tuple(hosts)


@dataclass(frozen=True, slots=True)
class WriterConflict:
    """The non-retryable result of a write-producing use case on a writer that
    sees another host's marker."""

    other_writers: tuple[HostId, ...]

    def reason(self) -> str:
        """What a job refused for it records as ``last_error``."""
        return (
            f"writer_conflict: marker of host {', '.join(self.other_writers)} present"
        )


@dataclass(frozen=True, slots=True)
class WriterStanding:
    """This host's marker, the other writers' markers, and whether a writer is
    in conflict (``writer.status``)."""

    role: HostRole
    host_id: HostId
    own_marker: bool
    other_writers: tuple[HostId, ...]

    @property
    def conflict(self) -> bool:
        return self.role is HostRole.WRITER and bool(self.other_writers)

    def refusal(self) -> WriterConflict | None:
        return WriterConflict(self.other_writers) if self.conflict else None


def writer_standing(
    snapshot: Snapshot | None, roots: OwnedRoots, host_id: HostId, role: HostRole
) -> WriterStanding:
    """This host's standing read from the latest tree (none: no markers)."""
    hosts = () if snapshot is None else markers_in(snapshot, roots)
    others = tuple(h for h in hosts if h != host_id)[:MAX_OTHER_WRITERS]
    return WriterStanding(
        role=role, host_id=host_id, own_marker=host_id in hosts, other_writers=others
    )


def marker_operations(roots: OwnedRoots, host_id: HostId) -> tuple[Operation, ...]:
    """Create ``Dynomark`` (path-idempotent) and this host's marker directly in
    it."""
    dynomark = roots.dynomark
    marker = OpCreateFolder(index=0, parent=dynomark, title=marker_title(host_id))
    if not dynomark.names:
        return (marker,)
    create = OpCreateFolder(
        index=0,
        parent=dynomark.prefix(len(dynomark.names) - 1),
        title=dynomark.names[-1],
    )
    return (create, OpCreateFolder(index=1, parent=dynomark, title=marker.title))
