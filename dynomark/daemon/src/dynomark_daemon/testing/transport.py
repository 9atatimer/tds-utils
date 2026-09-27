"""A recording ``TransportPort``: every push kept, in order, with its profile."""

from dynomark_daemon.domain.events import Event
from dynomark_daemon.domain.ids import ProfileId


class RecordingTransport:
    def __init__(self) -> None:
        self.pushed: list[tuple[ProfileId, Event]] = []

    def push(self, profile_id: ProfileId, event: Event) -> None:
        self.pushed.append((profile_id, event))

    def events_for(self, profile_id: ProfileId) -> list[Event]:
        return [event for profile, event in self.pushed if profile == profile_id]
