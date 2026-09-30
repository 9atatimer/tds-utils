"""Seam: daemon -> extension delivery (native-messaging shim / future HTTPS).

Requests arrive through the transport adapter, which calls use cases; the
use cases only ever push events. Events are durable in the store until
acknowledged, so a push to a profile with no live connection is not an
error: it is delivered on the next ``events.replay``.
"""

from typing import Protocol

from dynomark_daemon.domain.events import Event
from dynomark_daemon.domain.ids import ProfileId


class TransportPort(Protocol):
    def push(self, profile_id: ProfileId, event: Event) -> None:
        """Send ``event`` to the connection of ``profile_id``, if there is one."""
        ...

    def fits(self, event: Event) -> bool:
        """Whether ``event`` fits one frame to the extension (1 MiB)."""
        ...
