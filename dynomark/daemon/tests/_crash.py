"""A store that dies at one chosen write: a daemon killed mid-use-case.

``kill_at(write, when)`` arms the store; the next call of ``write`` whose
first argument passes ``when`` raises ``SystemExit`` before it writes, and
the store disarms. A unit of work open around it rolls back, as a crash
before the commit would. The test then drives the same store again, as a
restarted daemon over the same file would.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from dynomark_daemon.domain.batch import BatchRecord
from dynomark_daemon.domain.bookmark import CorpusEntry, Save
from dynomark_daemon.domain.diff import DiffItem, TreeDiff
from dynomark_daemon.domain.events import Event
from dynomark_daemon.domain.ids import (
    EventId,
    JobId,
    NodeId,
    ProfileId,
    RequestId,
    SnapshotId,
)
from dynomark_daemon.domain.job import Job
from dynomark_daemon.domain.placement import MoveFeedback, Placement
from dynomark_daemon.domain.tree import FolderFlags, FolderPath, Snapshot
from dynomark_daemon.testing.store import InMemoryCorpusStore


def _always(_value: object) -> bool:
    return True


@dataclass(frozen=True, slots=True)
class _Armed:
    write: str
    when: Callable[[object], bool]


class DyingStore(InMemoryCorpusStore):
    def __init__(self) -> None:
        super().__init__()
        self._armed: _Armed | None = None

    def kill_at(self, write: str, when: Callable[[object], bool] = _always) -> None:
        """Die at the next ``write`` whose first argument passes ``when``."""
        self._armed = _Armed(write, when)

    @property
    def armed(self) -> bool:
        """Still armed: the kill has not happened."""
        return self._armed is not None

    def _dies(self, write: str, value: object) -> None:
        armed = self._armed
        if armed is not None and armed.write == write and armed.when(value):
            self._armed = None
            raise SystemExit(f"killed at {write}")

    def put_entry(self, entry: CorpusEntry) -> None:
        self._dies("put_entry", entry)
        super().put_entry(entry)

    def put_placement(self, placement: Placement) -> None:
        self._dies("put_placement", placement)
        super().put_placement(placement)

    def put_job(self, job: Job) -> None:
        self._dies("put_job", job)
        super().put_job(job)

    def put_save(self, job_id: JobId, save: Save) -> None:
        self._dies("put_save", job_id)
        super().put_save(job_id, save)

    def put_batch(self, record: BatchRecord) -> None:
        self._dies("put_batch", record)
        super().put_batch(record)

    def put_tree_snapshot(self, snapshot: Snapshot) -> None:
        self._dies("put_tree_snapshot", snapshot)
        super().put_tree_snapshot(snapshot)

    def put_snapshot(self, snapshot_id: SnapshotId, snapshot: Snapshot) -> None:
        self._dies("put_snapshot", snapshot_id)
        super().put_snapshot(snapshot_id, snapshot)

    def put_feedback(self, feedback: MoveFeedback) -> None:
        self._dies("put_feedback", feedback)
        super().put_feedback(feedback)

    def put_diff(self, diff: TreeDiff) -> None:
        self._dies("put_diff", diff)
        super().put_diff(diff)

    def put_diff_item(self, item: DiffItem) -> None:
        self._dies("put_diff_item", item)
        super().put_diff_item(item)

    def put_event(self, profile_id: ProfileId, event: Event) -> None:
        self._dies("put_event", event)
        super().put_event(profile_id, event)

    def mark_pushed(self, profile_id: ProfileId, event_ids: Iterable[EventId]) -> None:
        ids = list(event_ids)
        self._dies("mark_pushed", ids)
        super().mark_pushed(profile_id, ids)

    def ack_events(self, profile_id: ProfileId, event_ids: Iterable[EventId]) -> None:
        ids = list(event_ids)
        self._dies("ack_events", ids)
        super().ack_events(profile_id, ids)

    def put_folder_flags(self, node_id: NodeId, flags: FolderFlags) -> None:
        self._dies("put_folder_flags", flags)
        super().put_folder_flags(node_id, flags)

    def bind_writer_profile(self, profile_id: ProfileId) -> None:
        self._dies("bind_writer_profile", profile_id)
        super().bind_writer_profile(profile_id)

    def put_follow_up(self, profile_id: ProfileId, path: FolderPath) -> None:
        self._dies("put_follow_up", path)
        super().put_follow_up(profile_id, path)

    def put_request(self, request_id: RequestId, fingerprint: str) -> None:
        self._dies("put_request", request_id)
        super().put_request(request_id, fingerprint)
