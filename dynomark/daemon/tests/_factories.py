"""Builder functions for domain values (testing-python skill, Test Data)."""

from dynomark_daemon.domain.batch import (
    BatchRecord,
    BatchState,
    Expect,
    Operation,
    OpMove,
    WriteBatch,
)
from dynomark_daemon.domain.bookmark import (
    Bookmark,
    Capture,
    CaptureSource,
    CorpusEntry,
    Embedding,
    Identity,
)
from dynomark_daemon.domain.diff import DiffAction, DiffItem, DiffKind, TreeDiff
from dynomark_daemon.domain.ids import (
    BatchId,
    DiffId,
    FeedbackId,
    ItemId,
    JobId,
    NodeId,
    ProfileId,
)
from dynomark_daemon.domain.job import Job, JobState
from dynomark_daemon.domain.placement import (
    MoveFeedback,
    Placement,
    PlacementReason,
)
from dynomark_daemon.domain.tree import (
    FolderPath,
    NodeKind,
    OutlineFolder,
    RootIds,
    RootKey,
    Snapshot,
    SnapshotNode,
    TreeOutline,
)


def make_path(*names: str) -> FolderPath:
    return FolderPath(root=RootKey.BAR, names=names)


def make_bookmark(
    url: str = "https://tokio.rs/tokio/tutorial",
    *,
    node_id: str = "42",
    title: str = "Tokio tutorial",
    path: FolderPath | None = None,
) -> Bookmark:
    return Bookmark(
        node_id=NodeId(node_id),
        url=url,
        title=title,
        path=path or make_path("Follow Up"),
        date_added=1_790_000_000_000,
    )


def make_capture(
    text: str = "", *, source: CaptureSource = CaptureSource.TAB
) -> Capture:
    return Capture(source=source, text=text)


def make_entry(
    identity: str = "https://tokio.rs/tokio/tutorial",
    *,
    title: str = "Tokio tutorial",
    summary: str = "",
    tags: tuple[str, ...] = (),
    text: str = "",
    vector: tuple[float, ...] = (1.0, 0.0),
) -> CorpusEntry:
    return CorpusEntry(
        identity=Identity(identity),
        bookmark=make_bookmark(identity, title=title),
        capture=make_capture(text),
        summary=summary,
        tags=tags,
        embedding=Embedding(vector=vector, model_id="fake:hashing"),
        indexed_at=1_790_000_001_000,
    )


def make_placement(
    identity: str = "https://tokio.rs/tokio/tutorial",
    *,
    folder: FolderPath | None = None,
) -> Placement:
    return Placement(
        identity=Identity(identity),
        reason=PlacementReason(
            folder=folder or make_path("Dynomark", "Rust"),
            neighbours=(),
            rationale="nearest neighbours",
            feedback_ids=(),
            model_id="fake:scripted",
        ),
        created_at=1_790_000_002_000,
    )


def make_job(
    job_id: str = "job-1",
    *,
    profile_id: str = "profile-a",
    node_id: str = "42",
    identity: str = "https://tokio.rs/tokio/tutorial",
    state: JobState = JobState.QUEUED,
) -> Job:
    return Job(
        job_id=JobId(job_id),
        profile_id=ProfileId(profile_id),
        node_id=NodeId(node_id),
        identity=Identity(identity),
        state=state,
        seq=1,
        attempts=0,
        backfill=False,
        updated_at=1_790_000_000_000,
    )


def make_move_op(index: int = 0, *, node_id: str = "42") -> OpMove:
    return OpMove(
        index=index,
        node_id=NodeId(node_id),
        to=make_path("Dynomark", "Rust"),
        expect=Expect(parent_id=NodeId("5")),
    )


def make_batch(
    batch_id: str = "batch-1",
    *,
    state: BatchState = BatchState.PROPOSED,
    created_at: int = 1_790_000_003_000,
    operations: tuple[Operation, ...] | None = None,
) -> BatchRecord:
    ops = operations or (make_move_op(),)
    return BatchRecord(
        batch=WriteBatch(batch_id=BatchId(batch_id), operations=ops, inverse=ops),
        state=state,
        created_at=created_at,
    )


def make_snapshot(taken_at: int = 1_790_000_000_000, *, title: str = "Bar") -> Snapshot:
    return Snapshot(
        taken_at=taken_at,
        root_ids=RootIds(bar=NodeId("1"), other=NodeId("2")),
        nodes=(
            SnapshotNode(
                node_id=NodeId("1"),
                parent_id=None,
                index=0,
                kind=NodeKind.FOLDER,
                title=title,
                date_added=0,
            ),
        ),
    )


def make_feedback(
    feedback_id: str = "fb-1", *, observed_at: int = 1_790_000_004_000
) -> MoveFeedback:
    return MoveFeedback(
        feedback_id=FeedbackId(feedback_id),
        identity=Identity("https://tokio.rs/tokio/tutorial"),
        from_path=make_path("Dynomark", "Rust"),
        to_path=make_path("Dynomark", "Rust", "Async"),
        observed_at=observed_at,
    )


def make_diff_item(
    item_id: str = "item-1",
    *,
    diff_id: str = "diff-1",
    accepted_at: int | None = None,
) -> DiffItem:
    return DiffItem(
        item_id=ItemId(item_id),
        diff_id=DiffId(diff_id),
        action=DiffAction.MOVE,
        description="Move Async under Concurrency",
        operations=(make_move_op(),),
        accepted_at=accepted_at,
    )


def make_diff(
    diff_id: str = "diff-1",
    *,
    proposed_at: int = 1_790_000_005_000,
    items: tuple[DiffItem, ...] | None = None,
) -> TreeDiff:
    return TreeDiff(
        diff_id=DiffId(diff_id),
        kind=DiffKind.REBUILD,
        proposed_at=proposed_at,
        items=items if items is not None else (make_diff_item(diff_id=diff_id),),
    )


def make_outline_folder(
    *names: str,
    node_id: str | None = None,
    locked: bool = False,
    pinned: bool = False,
    item_count: int = 0,
) -> OutlineFolder:
    return OutlineFolder(
        node_id=NodeId(node_id or "n-" + "-".join(names)),
        path=make_path(*names),
        pinned=pinned,
        locked=locked,
        item_count=item_count,
    )


def make_outline(*folders: OutlineFolder) -> TreeOutline:
    """The Dynomark subtree: ``Dynomark`` itself plus ``folders``."""
    return TreeOutline(
        root=make_path("Dynomark"),
        folders=(make_outline_folder("Dynomark"), *folders),
    )
