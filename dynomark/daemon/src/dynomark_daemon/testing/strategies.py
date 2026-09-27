"""Hypothesis strategies for domain values that fit contract v1's caps.

Test support only (imports hypothesis, a dev dependency); never imported by
production code. Values stay inside the wire caps so that a mapping
failure is a mapping bug, not an oversize input.
"""

from hypothesis import strategies as st

from dynomark_daemon.domain.batch import (
    BatchRecord,
    BatchState,
    Expect,
    OpCreate,
    OpCreateFolder,
    Operation,
    OpMove,
    OpRemove,
    UndoDrop,
    UndoDropReason,
    WriteBatch,
)
from dynomark_daemon.domain.bookmark import CaptureSource, Identity
from dynomark_daemon.domain.diff import DiffAction, DiffItem, DiffKind, TreeDiff
from dynomark_daemon.domain.events import BatchOffered, DiffProposed, JobUpdated
from dynomark_daemon.domain.ids import (
    BatchId,
    DiffId,
    EventId,
    ItemId,
    JobId,
    NodeId,
    ProfileId,
)
from dynomark_daemon.domain.job import Job, JobState
from dynomark_daemon.domain.tree import FolderPath, RootKey

ID_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-"
NODE_ALPHABET = ID_ALPHABET.replace(":", "")
EPOCH_MS = st.integers(min_value=0, max_value=2**53 - 1)

ids = st.text(ID_ALPHABET, min_size=1, max_size=16)
node_ids = st.text(NODE_ALPHABET, min_size=1, max_size=12).map(NodeId)
titles = st.text(max_size=12)
identities = st.text(min_size=1, max_size=40).map(lambda s: Identity("https://" + s))
folder_paths = st.builds(
    FolderPath,
    root=st.sampled_from(RootKey),
    names=st.lists(titles, max_size=4).map(tuple),
)
expects = st.builds(
    Expect,
    parent_id=node_ids,
    parent_path=st.none() | folder_paths,
    empty=st.booleans(),
)


def _operation(index: int) -> st.SearchStrategy[Operation]:
    return st.one_of(
        st.builds(
            OpCreateFolder, index=st.just(index), parent=folder_paths, title=titles
        ),
        st.builds(
            OpCreate,
            index=st.just(index),
            parent=folder_paths,
            title=titles,
            url=st.text(min_size=1, max_size=30),
        ),
        st.builds(
            OpMove,
            index=st.just(index),
            node_id=node_ids,
            to=folder_paths,
            expect=expects,
        ),
        st.builds(OpRemove, index=st.just(index), node_id=node_ids, expect=expects),
    )


@st.composite
def operations(draw: st.DrawFn, max_size: int = 5) -> tuple[Operation, ...]:
    """1..max_size operations whose ``index`` equals their position."""
    count = draw(st.integers(min_value=1, max_value=max_size))
    return tuple(draw(_operation(i)) for i in range(count))


write_batches = st.builds(
    WriteBatch,
    batch_id=ids.map(BatchId),
    operations=operations(),
    inverse=operations(),
    diff_item_id=st.none() | ids.map(ItemId),
)

jobs = st.builds(
    Job,
    job_id=ids.map(JobId),
    profile_id=ids.map(ProfileId),
    node_id=node_ids,
    identity=identities,
    state=st.sampled_from(JobState),
    seq=st.integers(min_value=1, max_value=2**53 - 1),
    attempts=st.integers(min_value=0, max_value=100),
    backfill=st.booleans(),
    updated_at=EPOCH_MS,
    capture_source=st.none() | st.sampled_from(CaptureSource),
    last_error=st.none() | st.text(max_size=20),
    batch_id=st.none() | ids.map(BatchId),
)

diff_items = st.builds(
    DiffItem,
    item_id=ids.map(ItemId),
    diff_id=ids.map(DiffId),
    action=st.sampled_from(DiffAction),
    description=st.text(min_size=1, max_size=20),
    operations=operations(),
    accepted_at=st.none() | EPOCH_MS,
    batch_id=st.none() | ids.map(BatchId),
)

tree_diffs = st.builds(
    TreeDiff,
    diff_id=ids.map(DiffId),
    kind=st.sampled_from(DiffKind),
    proposed_at=EPOCH_MS,
    items=st.lists(diff_items, max_size=3).map(tuple),
)

batch_records = st.builds(
    BatchRecord,
    batch=write_batches,
    state=st.sampled_from(BatchState),
    created_at=EPOCH_MS,
    job_id=st.none() | ids.map(JobId),
    identity=st.none() | identities,
    undoes=st.none() | ids.map(BatchId),
    undone_by=st.none() | ids.map(BatchId),
    report=st.lists(
        st.builds(
            UndoDrop,
            index=st.integers(min_value=0, max_value=999),
            reason=st.sampled_from(UndoDropReason),
        ),
        max_size=3,
    ).map(tuple),
)

events = st.one_of(
    st.builds(JobUpdated, event_id=ids.map(EventId), job=jobs),
    st.builds(BatchOffered, event_id=ids.map(EventId), batch=write_batches),
    st.builds(DiffProposed, event_id=ids.map(EventId), diff=tree_diffs),
)
