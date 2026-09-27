"""A recording ``TransportPort``: every push kept, in order, with its profile.

``fits`` answers from the function it was built with (every event fits by
default), so a test can make one event too large for a frame.
"""

from collections.abc import Callable

from dynomark_daemon.domain.events import Event
from dynomark_daemon.domain.ids import ProfileId


def _always(event: Event) -> bool:
    return True


class RecordingTransport:
    def __init__(self, *, fits: Callable[[Event], bool] = _always) -> None:
        self.pushed: list[tuple[ProfileId, Event]] = []
        self._fits = fits

    def push(self, profile_id: ProfileId, event: Event) -> None:
        self.pushed.append((profile_id, event))

    def fits(self, event: Event) -> bool:
        return self._fits(event)

    def events_for(self, profile_id: ProfileId) -> list[Event]:
        return [event for profile, event in self.pushed if profile == profile_id]
