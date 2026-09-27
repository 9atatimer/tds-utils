"""Contract v1 shared values: one model per non-message ``$defs`` entry.

Names follow messages.schema.json so a reader can put the two side by
side. Enums are ``Literal`` string sets (exact, case-sensitive).
"""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from dynomark_daemon.wire.base import (
    Count,
    Detail,
    EpochMs,
    Id,
    Identity,
    ModelId,
    NodeId,
    OpIndex,
    Tag,
    Title,
    TrueOnly,
    Url,
    WireModel,
)

# --- Enums ---

RootKey = Literal["bar", "other", "mobile", "menu"]
HostRole = Literal["writer", "reader"]
CaptureSource = Literal["tab", "background_tab", "fetch", "none"]
ExtensionCaptureSource = Literal["tab", "background_tab", "none"]
"""``Capture.source`` on the wire: ``fetch`` is daemon-only."""
JobState = Literal[
    "QUEUED", "CAPTURING", "ENRICHED", "PLACED", "FILED", "INDEXED", "FAILED"
]
DiffKind = Literal["audit", "rebuild"]
MoveOrigin = Literal["user", "extension"]
HitTier = Literal["local", "corpus"]
HelloMode = Literal["full", "read_only", "refused"]
ErrorCode = Literal[
    "version_mismatch",
    "hello_required",
    "not_writer",
    "writer_conflict",
    "not_found",
    "invalid",
    "stale_cursor",
    "busy",
    "internal",
    "superseded",
]
BatchState = Literal["PROPOSED", "APPLIED", "PARTIAL", "REJECTED"]
NodeKind = Literal["folder", "bookmark", "separator"]
SkipReason = Literal["node_missing", "parent_mismatch", "not_empty"]
FailReason = Literal["parent_missing", "browser_error"]
RejectReason = Literal["boundary", "invalid", "writer_conflict"]
UndoDropReason = Literal["node_moved", "node_missing", "not_empty"]
DiffAction = Literal["add", "move", "merge"]


# --- Tree ---


class FolderPath(WireModel):
    root: RootKey
    names: Annotated[list[Title], Field(max_length=64)]


class OwnedRoots(WireModel):
    follow_up: FolderPath
    dynomark: FolderPath
    graveyard: FolderPath


class RootIds(WireModel):
    bar: NodeId
    other: NodeId
    mobile: NodeId | None = None
    menu: NodeId | None = None


class SnapshotNode(WireModel):
    id: NodeId
    parent_id: NodeId | None
    index: Count
    kind: NodeKind
    title: Annotated[str, Field(max_length=4096)]
    url: Annotated[str, Field(min_length=1, max_length=65536)] | None = None
    truncated: TrueOnly | None = None
    date_added: EpochMs

    @model_validator(mode="after")
    def _only_a_bookmark_carries_url(self) -> Self:
        if (self.kind == "bookmark") != (self.url is not None):
            raise ValueError("url is required on a bookmark and absent otherwise")
        return self


class Snapshot(WireModel):
    taken_at: EpochMs
    root_ids: RootIds
    nodes: Annotated[list[SnapshotNode], Field(min_length=1, max_length=500000)]


class OutlineFolder(WireModel):
    node_id: NodeId
    path: FolderPath
    pinned: bool
    locked: bool
    item_count: Count


TreeOutline = Annotated[list[OutlineFolder], Field(max_length=1000)]


# --- Bookmark, capture, job ---


class Bookmark(WireModel):
    node_id: NodeId
    url: Url
    title: Title
    path: FolderPath
    date_added: EpochMs


class Capture(WireModel):
    source: ExtensionCaptureSource
    text: Annotated[str, Field(max_length=1048576)]
    title: Title | None = None

    @model_validator(mode="after")
    def _source_none_carries_no_text(self) -> Self:
        if self.source == "none" and self.text != "":
            raise ValueError("a capture with source none carries empty text")
        return self


class Job(WireModel):
    job_id: Id
    node_id: NodeId
    identity: Identity
    state: JobState
    seq: Annotated[int, Field(ge=1, le=2**53 - 1)]
    attempts: Count
    backfill: bool
    capture_source: CaptureSource | None = None
    last_error: Detail | None = None
    batch_id: Id | None = None


# --- Operations and batches ---


class Expect(WireModel):
    """``Expect`` as every op uses it: ``parent_id`` is always required."""

    parent_path: FolderPath | None = None
    parent_id: NodeId
    empty: TrueOnly | None = None


class OpCreateFolder(WireModel):
    op: Literal["create_folder"]
    index: OpIndex
    parent: FolderPath
    title: Title


class OpCreate(WireModel):
    op: Literal["create"]
    index: OpIndex
    parent: FolderPath
    title: Title
    url: Url


class OpMove(WireModel):
    op: Literal["move"]
    index: OpIndex
    node_id: NodeId
    to: FolderPath
    expect: Expect


class OpRemove(WireModel):
    op: Literal["remove"]
    index: OpIndex
    node_id: NodeId
    expect: Expect


Operation = Annotated[
    OpCreateFolder | OpCreate | OpMove | OpRemove, Field(discriminator="op")
]


class WriteBatch(WireModel):
    batch_id: Id
    operations: Annotated[list[Operation], Field(min_length=1, max_length=1000)]
    diff_item_id: Id | None = None


class OpApplied(WireModel):
    index: OpIndex
    node_id: NodeId
    changed: bool


class OpSkipped(WireModel):
    index: OpIndex
    reason: SkipReason


class OpFailed(WireModel):
    index: OpIndex
    reason: FailReason
    detail: Detail | None = None


class ReceiptApplied(WireModel):
    state: Literal["APPLIED"]
    batch_id: Id
    snapshot: Snapshot | None = None
    snapshot_omitted: TrueOnly | None = None
    pre_batch: bool
    applied: Annotated[list[OpApplied], Field(max_length=1000)]
    skipped: Annotated[list[OpSkipped], Field(max_length=1000)]

    @model_validator(mode="after")
    def _snapshot_xor_omitted(self) -> Self:
        return self.require_exactly_one("snapshot", "snapshot_omitted")


class ReceiptPartial(WireModel):
    state: Literal["PARTIAL"]
    batch_id: Id
    snapshot: Snapshot | None = None
    snapshot_omitted: TrueOnly | None = None
    pre_batch: bool
    applied: Annotated[list[OpApplied], Field(max_length=1000)]
    skipped: Annotated[list[OpSkipped], Field(max_length=1000)]
    failed: OpFailed

    @model_validator(mode="after")
    def _snapshot_xor_omitted(self) -> Self:
        return self.require_exactly_one("snapshot", "snapshot_omitted")


class ReceiptRejected(WireModel):
    state: Literal["REJECTED"]
    batch_id: Id
    snapshot: Snapshot | None = None
    snapshot_omitted: TrueOnly | None = None
    pre_batch: bool
    reason: RejectReason
    detail: Detail | None = None

    @model_validator(mode="after")
    def _snapshot_xor_omitted(self) -> Self:
        return self.require_exactly_one("snapshot", "snapshot_omitted")


BatchReceipt = Annotated[
    ReceiptApplied | ReceiptPartial | ReceiptRejected, Field(discriminator="state")
]


class UndoDrop(WireModel):
    index: OpIndex
    reason: UndoDropReason


class BatchSummary(WireModel):
    batch_id: Id
    state: BatchState
    created_at: EpochMs
    job_id: Id | None = None
    identity: Identity | None = None
    diff_item_id: Id | None = None
    undoes: Id | None = None
    undone_by: Id | None = None


# --- Moves, search, chat, placement ---


class Move(WireModel):
    node_id: NodeId
    url: Url | None = None
    from_: FolderPath = Field(alias="from")
    to: FolderPath
    origin: MoveOrigin
    observed_at: EpochMs


class LocalIndexRow(WireModel):
    identity: Identity
    title: Title
    path: FolderPath
    tags: Annotated[list[Tag], Field(max_length=32)]
    summary: Annotated[str, Field(max_length=512)]


class Hit(WireModel):
    identity: Identity
    title: Title
    path: FolderPath
    score: Annotated[float, Field(ge=0, le=1)]
    tier: HitTier


class CorpusHit(Hit):
    """A ``Hit`` inside ``search.result``: always tier ``corpus``."""

    tier: Literal["corpus"]


class EntryRef(WireModel):
    identity: Identity
    title: Title
    path: FolderPath


Citation = EntryRef


class Turn(WireModel):
    question: Annotated[str, Field(min_length=1, max_length=8192)]
    answer: Annotated[str, Field(max_length=65536)]


class Answer(WireModel):
    text: Annotated[str, Field(max_length=65536)]
    citations: Annotated[list[Citation], Field(max_length=50)]
    external_urls: Annotated[list[Url], Field(max_length=50)]


class PlacementReason(WireModel):
    identity: Identity
    folder: FolderPath
    neighbours: Annotated[list[EntryRef], Field(max_length=50)]
    rationale: Annotated[str, Field(max_length=8192)]
    feedback_ids: Annotated[list[Id], Field(max_length=50)]
    model_id: ModelId
    created_at: EpochMs


# --- Diffs, status ---


class TreeDiff(WireModel):
    diff_id: Id
    kind: DiffKind
    proposed_at: EpochMs
    item_count: Count
    unaccepted_count: Count


class DiffItem(WireModel):
    item_id: Id
    diff_id: Id
    action: DiffAction
    description: Annotated[str, Field(min_length=1, max_length=4096)]
    operations: Annotated[list[Operation], Field(min_length=1, max_length=100)]
    accepted_at: EpochMs | None
    batch_id: Id | None = None
    batch_state: BatchState | None = None


class ModelInfo(WireModel):
    id: ModelId
    local: bool


class Models(WireModel):
    embedding: ModelInfo
    completion: ModelInfo
