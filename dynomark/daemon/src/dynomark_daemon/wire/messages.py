"""Contract v1 messages: one model per message ``$defs`` entry, and the union.

Every frame is exactly one message, discriminated by ``type``. A request
carries ``id``, a response ``re``, an event ``event_id``
(contract/v1/README.md, Envelope). ``hello``, ``hello.result`` and
``error`` are frozen and accept any ``v >= 1``; every other message pins
``v`` to ``CONTRACT_VERSION``.
"""

from collections.abc import Mapping
from typing import Annotated, Final, Literal, Self, get_args

from pydantic import Field, TypeAdapter, model_validator

from dynomark_daemon.wire.base import (
    Count,
    Cursor,
    Detail,
    EpochMs,
    FrozenVersion,
    HostId,
    Id,
    Identity,
    NodeId,
    Url,
    Version,
    WireModel,
)
from dynomark_daemon.wire.values import (
    Answer,
    BatchReceipt,
    BatchSummary,
    Bookmark,
    Capture,
    CorpusHit,
    DiffItem,
    DiffKind,
    ErrorCode,
    FolderPath,
    HelloMode,
    HostRole,
    Job,
    JobState,
    LocalIndexRow,
    Models,
    Move,
    OutlineFolder,
    OwnedRoots,
    PlacementReason,
    Snapshot,
    TreeDiff,
    TreeOutline,
    Turn,
    UndoDrop,
    WriteBatch,
)

# --- Page sizes (contract/v1/README.md, Size limits) ---

LARGE_PAGE: Final = 1000
SMALL_PAGE: Final = 100

LargeLimit = Annotated[int, Field(ge=1, le=LARGE_PAGE)]
SmallLimit = Annotated[int, Field(ge=1, le=SMALL_PAGE)]


# --- Handshake and errors (frozen) ---


class Hello(WireModel):
    v: FrozenVersion
    type: Literal["hello"]
    id: Id
    profile_id: Id
    follow_up: FolderPath


class HelloResult(WireModel):
    v: FrozenVersion
    type: Literal["hello.result"]
    re: Id
    host_id: HostId
    role: HostRole
    mode: HelloMode
    owned_roots: OwnedRoots


class Error(WireModel):
    v: FrozenVersion
    type: Literal["error"]
    re: Id | None
    code: ErrorCode
    message: Detail


# --- Jobs ---


class Ingest(WireModel):
    v: Version
    type: Literal["ingest"]
    id: Id
    bookmark: Bookmark
    capture: Capture | None = None
    backfill: bool


class IngestResult(WireModel):
    v: Version
    type: Literal["ingest.result"]
    re: Id
    job: Job


class JobRetry(WireModel):
    v: Version
    type: Literal["job.retry"]
    id: Id
    job_id: Id


class JobRetryResult(WireModel):
    v: Version
    type: Literal["job.retry.result"]
    re: Id
    job: Job


class JobList(WireModel):
    v: Version
    type: Literal["job.list"]
    id: Id
    state: JobState | None = None
    cursor: Cursor | None = None
    limit: LargeLimit | None = None


class JobListResult(WireModel):
    v: Version
    type: Literal["job.list.result"]
    re: Id
    jobs: Annotated[list[Job], Field(max_length=LARGE_PAGE)]
    next_cursor: Cursor | None


class JobUpdated(WireModel):
    v: Version
    type: Literal["job.updated"]
    event_id: Id
    job: Job


# --- Tree, moves, batches ---


class TreeSnapshot(WireModel):
    v: Version
    type: Literal["tree.snapshot"]
    id: Id
    snapshot: Snapshot


class TreeSnapshotResult(WireModel):
    v: Version
    type: Literal["tree.snapshot.result"]
    re: Id


class MoveObserved(WireModel):
    v: Version
    type: Literal["move.observed"]
    id: Id
    move: Move


class MoveObservedResult(WireModel):
    v: Version
    type: Literal["move.observed.result"]
    re: Id


class BatchOffer(WireModel):
    v: Version
    type: Literal["batch.offer"]
    event_id: Id
    batch: WriteBatch


class BatchReceiptMessage(WireModel):
    v: Version
    type: Literal["batch.receipt"]
    id: Id
    receipt: BatchReceipt


class BatchReceiptMessageResult(WireModel):
    v: Version
    type: Literal["batch.receipt.result"]
    re: Id


class BatchList(WireModel):
    v: Version
    type: Literal["batch.list"]
    id: Id
    cursor: Cursor | None = None
    limit: SmallLimit | None = None


class BatchListResult(WireModel):
    v: Version
    type: Literal["batch.list.result"]
    re: Id
    batches: Annotated[list[BatchSummary], Field(max_length=SMALL_PAGE)]
    next_cursor: Cursor | None


class Undo(WireModel):
    v: Version
    type: Literal["undo"]
    id: Id
    batch_id: Id


class UndoResult(WireModel):
    v: Version
    type: Literal["undo.result"]
    re: Id
    batch_id: Id | None
    undoes: Id
    dropped: Annotated[list[UndoDrop], Field(max_length=1000)]


# --- Events delivery ---


class EventsReplay(WireModel):
    v: Version
    type: Literal["events.replay"]
    id: Id


class EventsReplayResult(WireModel):
    v: Version
    type: Literal["events.replay.result"]
    re: Id
    count: Count


class EventsAck(WireModel):
    v: Version
    type: Literal["events.ack"]
    id: Id
    event_ids: Annotated[list[Id], Field(min_length=1, max_length=1000)]


class EventsAckResult(WireModel):
    v: Version
    type: Literal["events.ack.result"]
    re: Id


# --- Index, search, chat, placement ---


class IndexPull(WireModel):
    v: Version
    type: Literal["index.pull"]
    id: Id
    cursor: Cursor | None = None
    limit: LargeLimit | None = None


class IndexPullResult(WireModel):
    v: Version
    type: Literal["index.pull.result"]
    re: Id
    rows: Annotated[list[LocalIndexRow], Field(max_length=LARGE_PAGE)]
    next_cursor: Cursor | None


class Search(WireModel):
    v: Version
    type: Literal["search"]
    id: Id
    query: Annotated[str, Field(min_length=1, max_length=1024)]
    cursor: Cursor | None = None
    limit: SmallLimit | None = None


class SearchResult(WireModel):
    v: Version
    type: Literal["search.result"]
    re: Id
    hits: Annotated[list[CorpusHit], Field(max_length=SMALL_PAGE)]
    next_cursor: Cursor | None


class Ask(WireModel):
    v: Version
    type: Literal["ask"]
    id: Id
    question: Annotated[str, Field(min_length=1, max_length=8192)]
    history: Annotated[list[Turn], Field(max_length=50)]


class AskResult(WireModel):
    v: Version
    type: Literal["ask.result"]
    re: Id
    answer: Answer


class PlacementExplain(WireModel):
    v: Version
    type: Literal["placement.explain"]
    id: Id
    identity: Identity | None = None
    url: Url | None = None

    @model_validator(mode="after")
    def _identity_xor_url(self) -> Self:
        return self.require_exactly_one("identity", "url")


class PlacementExplainResult(WireModel):
    v: Version
    type: Literal["placement.explain.result"]
    re: Id
    reason: PlacementReason


# --- Diffs ---


class DiffPropose(WireModel):
    v: Version
    type: Literal["diff.propose"]
    id: Id
    kind: DiffKind


class DiffProposeResult(WireModel):
    v: Version
    type: Literal["diff.propose.result"]
    re: Id
    diff: TreeDiff


class DiffList(WireModel):
    v: Version
    type: Literal["diff.list"]
    id: Id
    cursor: Cursor | None = None
    limit: SmallLimit | None = None


class DiffListResult(WireModel):
    v: Version
    type: Literal["diff.list.result"]
    re: Id
    diffs: Annotated[list[TreeDiff], Field(max_length=SMALL_PAGE)]
    next_cursor: Cursor | None


class DiffProposed(WireModel):
    v: Version
    type: Literal["diff.proposed"]
    event_id: Id
    diff: TreeDiff


class DiffPage(WireModel):
    v: Version
    type: Literal["diff.page"]
    id: Id
    diff_id: Id
    cursor: Cursor | None = None
    limit: SmallLimit | None = None


class DiffPageResult(WireModel):
    v: Version
    type: Literal["diff.page.result"]
    re: Id
    diff: TreeDiff
    items: Annotated[list[DiffItem], Field(max_length=SMALL_PAGE)]
    next_cursor: Cursor | None


class DiffAccept(WireModel):
    v: Version
    type: Literal["diff.accept"]
    id: Id
    item_id: Id


class DiffAcceptResult(WireModel):
    v: Version
    type: Literal["diff.accept.result"]
    re: Id
    item_id: Id
    accepted_at: EpochMs
    batch_id: Id


# --- Outline, flags, writer, status ---


class OutlineGet(WireModel):
    v: Version
    type: Literal["outline.get"]
    id: Id
    cursor: Cursor | None = None
    limit: LargeLimit | None = None


class OutlineGetResult(WireModel):
    v: Version
    type: Literal["outline.get.result"]
    re: Id
    outline: TreeOutline
    next_cursor: Cursor | None


class FolderFlagsSet(WireModel):
    v: Version
    type: Literal["folder.flags.set"]
    id: Id
    node_id: NodeId
    path: FolderPath | None = None
    pinned: bool | None = None
    locked: bool | None = None

    @model_validator(mode="after")
    def _sets_at_least_one_flag(self) -> Self:
        if self.pinned is None and self.locked is None:
            raise ValueError("folder.flags.set changes pinned, locked, or both")
        return self


class FolderFlagsSetResult(WireModel):
    v: Version
    type: Literal["folder.flags.set.result"]
    re: Id
    folder: OutlineFolder


class WriterStatus(WireModel):
    v: Version
    type: Literal["writer.status"]
    id: Id


class WriterStatusResult(WireModel):
    v: Version
    type: Literal["writer.status.result"]
    re: Id
    role: HostRole
    host_id: HostId
    own_marker: bool
    other_writers: Annotated[list[HostId], Field(max_length=64)]
    conflict: bool

    @model_validator(mode="after")
    def _other_writers_is_a_set(self) -> Self:
        if len(set(self.other_writers)) != len(self.other_writers):
            raise ValueError("other_writers holds each host once")
        return self


class Status(WireModel):
    v: Version
    type: Literal["status"]
    id: Id


class StatusResult(WireModel):
    v: Version
    type: Literal["status.result"]
    re: Id
    role: HostRole
    host_id: HostId
    contract_version: Annotated[int, Field(ge=1)]
    models: Models
    queue_depth: Count


# --- The union ---

AnyMessage = (
    Hello
    | HelloResult
    | Ingest
    | IngestResult
    | JobRetry
    | JobRetryResult
    | JobList
    | JobListResult
    | TreeSnapshot
    | TreeSnapshotResult
    | MoveObserved
    | MoveObservedResult
    | BatchReceiptMessage
    | BatchReceiptMessageResult
    | EventsReplay
    | EventsReplayResult
    | EventsAck
    | EventsAckResult
    | IndexPull
    | IndexPullResult
    | Search
    | SearchResult
    | Ask
    | AskResult
    | PlacementExplain
    | PlacementExplainResult
    | Undo
    | UndoResult
    | BatchList
    | BatchListResult
    | DiffPropose
    | DiffProposeResult
    | DiffList
    | DiffListResult
    | DiffPage
    | DiffPageResult
    | DiffAccept
    | DiffAcceptResult
    | OutlineGet
    | OutlineGetResult
    | FolderFlagsSet
    | FolderFlagsSetResult
    | WriterStatus
    | WriterStatusResult
    | Status
    | StatusResult
    | Error
    | JobUpdated
    | BatchOffer
    | DiffProposed
)
Message = Annotated[AnyMessage, Field(discriminator="type")]

MESSAGE_ADAPTER: Final[TypeAdapter[AnyMessage]] = TypeAdapter(Message)


def _type_of(model: type[WireModel]) -> str:
    (literal,) = get_args(model.model_fields["type"].annotation)
    return str(literal)


MESSAGE_MODELS: Final[Mapping[str, type[AnyMessage]]] = {
    _type_of(model): model for model in get_args(AnyMessage)
}
"""Every message type string -> its wire model."""


def validate_message(body: bytes | str) -> AnyMessage:
    """Parse one frame body into its message model.

    Raises:
        pydantic.ValidationError: the body fails contract v1.
    """
    return MESSAGE_ADAPTER.validate_json(body)
