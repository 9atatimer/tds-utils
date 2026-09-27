"""Behaviors rows: A diff is proposed; A diff item is accepted; An audit item
may cross the boundary; the diff half of A reader host never writes
(DYNOMARK.DESIGN.md, Behaviors and Interfaces; The daemon, "Diffs"; Goal
8) -- ``propose_diff(kind, outline, own_bar, *, completion) -> TreeDiff``
and ``accept_diff_item(item, roots, role) -> WriteBatch or NotWriter``.

Contract v1 pins the rest: ``diff.propose`` is idempotent on its request
id (another body under a known id is ``invalid``) and reads the latest
``tree.snapshot``; ``diff.accept`` is idempotent on ``item_id``, records
``accepted_at`` and offers the batch; ``diff.page`` shows each accepted
item's batch and its state; ``diff.list`` is newest first.
"""

import pytest

from dynomark_daemon.app.diffs import (
    accept_diff,
    accept_diff_item,
    diff_items_page,
    list_diffs_page,
    propose_diff,
    request_diff,
)
from dynomark_daemon.app.errors import InvalidRequest, TreeNotReady, UnknownRecord
from dynomark_daemon.app.receipt import receive_receipt
from dynomark_daemon.app.tree import record_tree_snapshot
from dynomark_daemon.app.undo import Undone, undo
from dynomark_daemon.domain.batch import (
    BatchState,
    Expect,
    OpApplied,
    OpMove,
    ReceiptApplied,
    WriteBatch,
)
from dynomark_daemon.domain.diff import (
    DiffAction,
    DiffItem,
    DiffKind,
    DiffProposal,
    NotAccepted,
)
from dynomark_daemon.domain.events import BatchOffered
from dynomark_daemon.domain.ids import DiffId, NodeId, ProfileId, RequestId
from dynomark_daemon.domain.roles import HostRole, NotWriter
from dynomark_daemon.domain.tree import FolderFlags, FolderPath, RootKey, TreeOutline
from dynomark_daemon.testing.clock import FakeClock, SequentialIds
from dynomark_daemon.testing.completion import ProposeDiffCall, ScriptedCompletion
from dynomark_daemon.testing.store import InMemoryCorpusStore
from tests._factories import (
    make_diff_item,
    make_node,
    make_outline,
    make_outline_folder,
    make_path,
    make_roots,
    make_tree,
)

A = ProfileId("profile-a")
BAR = FolderPath(root=RootKey.BAR, names=())
RUST = make_path("Dynomark", "Rust")
ASYNC = make_path("Dynomark", "Rust", "Async")
READING = make_path("Reading")
TREE = make_tree(
    make_node("10", "1", "Follow Up"),
    make_node("11", "1", "Dynomark", index=1),
    make_node("12", "1", "Graveyard", index=2),
    make_node("30", "1", "Reading", index=3),
    make_node("14", "11", "Rust"),
    make_node("17", "11", "Pinned", index=1),
    make_node("16", "14", "Async"),
)


def _move(node_id: str, to: FolderPath, parent_id: str, parent: FolderPath) -> OpMove:
    return OpMove(
        index=0,
        node_id=NodeId(node_id),
        to=to,
        expect=Expect(parent_id=NodeId(parent_id), parent_path=parent),
    )


ASYNC_TO_CONCURRENCY = DiffProposal(
    action=DiffAction.MOVE,
    description="Move Async up to Dynomark",
    operations=(_move("16", make_path("Dynomark"), "14", RUST),),
)
PINNED_TO_RUST = DiffProposal(
    action=DiffAction.MOVE,
    description="Move Pinned under Rust",
    operations=(_move("17", RUST, "11", make_path("Dynomark")),),
)
ASYNC_TO_READING = DiffProposal(
    action=DiffAction.MOVE,
    description="Move Async to your Reading folder",
    operations=(_move("16", READING, "14", RUST),),
)


class Writer:
    """A writer daemon's store over fakes, holding TREE with Pinned pinned."""

    def __init__(self, *proposals: tuple[DiffProposal, ...]) -> None:
        self.store = InMemoryCorpusStore()
        self.store.put_tree_snapshot(TREE)
        self.store.put_folder_flags(
            NodeId("17"), FolderFlags(pinned=True, locked=False)
        )
        self.completion = ScriptedCompletion(propose_diff=list(proposals))
        self.clock, self.ids = FakeClock(start_ms=1_000), SequentialIds()

    def propose(self, kind: DiffKind, request_id: str = "req-1") -> DiffItem:
        diff = request_diff(
            RequestId(request_id),
            kind,
            HostRole.WRITER,
            make_roots(),
            store=self.store,
            completion=self.completion,
            clock=self.clock,
            ids=self.ids,
        )
        (item,) = diff.items
        return item

    def accept(
        self, item: DiffItem, role: HostRole = HostRole.WRITER
    ) -> DiffItem | NotWriter:
        return accept_diff(
            item.item_id,
            role,
            make_roots(),
            A,
            store=self.store,
            clock=self.clock,
            ids=self.ids,
        )


# --- Proposing ---


def test_a_proposed_diff_has_items_and_no_batch() -> None:
    """Given the two outlines and a completion proposing a move and a move of a
    pinned folder, When a rebuild is proposed, Then the diff holds the one
    item that keeps the rules, unaccepted, and no batch exists."""
    completion = ScriptedCompletion(
        propose_diff=[(ASYNC_TO_CONCURRENCY, PINNED_TO_RUST)]
    )
    outline = make_outline(
        make_outline_folder("Dynomark", "Rust", node_id="14"),
        make_outline_folder("Dynomark", "Rust", "Async", node_id="16"),
        make_outline_folder("Dynomark", "Pinned", node_id="17", pinned=True),
    )

    diff = propose_diff(
        DiffKind.REBUILD,
        outline,
        TreeOutline(root=BAR, folders=()),
        make_roots(),
        completion=completion,
        clock=FakeClock(start_ms=7),
        ids=SequentialIds(),
    )

    assert diff.kind is DiffKind.REBUILD and diff.proposed_at == 7
    (item,) = diff.items
    assert item.operations == ASYNC_TO_CONCURRENCY.operations
    assert item.accepted_at is None and item.batch_id is None


def test_request_diff_shows_the_model_both_outlines_and_stores_the_diff() -> None:
    """Given a tree with a Dynomark subtree and a Reading folder in the bar, When
    an audit is requested, Then the completion sees the Dynomark outline and
    the user's own bar (no owned folder in it), the vetted items are stored,
    and no batch exists."""
    writer = Writer((ASYNC_TO_READING, PINNED_TO_RUST))

    item = writer.propose(DiffKind.AUDIT)

    (call,) = writer.completion.calls
    assert isinstance(call, ProposeDiffCall) and call.kind is DiffKind.AUDIT
    assert {f.path for f in call.outline.folders} == {
        make_path("Dynomark"),
        RUST,
        ASYNC,
        make_path("Dynomark", "Pinned"),
    }
    assert {f.path for f in call.own_bar.folders} == {BAR, READING}
    assert item.accepted_at is None and item.operations[0].index == 0
    stored = writer.store.get_diff(item.diff_id)
    assert stored is not None and stored.items == (item,)
    assert writer.store.list_batches() == []


def test_request_diff_with_a_known_id_returns_the_same_diff_once() -> None:
    """Given a proposed diff, When the same request id arrives again with the
    same body, Then the same diff is returned and the model is not asked
    again; with another body it is invalid."""
    writer = Writer((ASYNC_TO_CONCURRENCY,))
    first = writer.propose(DiffKind.REBUILD)

    again = writer.propose(DiffKind.REBUILD)

    assert again == first and len(writer.completion.calls) == 1
    with pytest.raises(InvalidRequest):
        writer.propose(DiffKind.AUDIT)


def test_request_diff_before_any_tree_snapshot_is_not_ready() -> None:
    """Given a writer with no tree snapshot, When a diff is requested, Then it
    is not ready (busy): an audit must compare against the current bar."""
    with pytest.raises(TreeNotReady):
        request_diff(
            RequestId("req-1"),
            DiffKind.AUDIT,
            HostRole.WRITER,
            make_roots(),
            store=InMemoryCorpusStore(),
            completion=ScriptedCompletion(),
            clock=FakeClock(),
            ids=SequentialIds(),
        )


def test_request_diff_on_a_reader_is_invalid() -> None:
    """Given a reader (which keeps no tree), When a diff is requested, Then the
    request is one it cannot act on, and no model is asked."""
    completion = ScriptedCompletion()
    with pytest.raises(InvalidRequest):
        request_diff(
            RequestId("req-1"),
            DiffKind.REBUILD,
            HostRole.READER,
            make_roots(),
            store=InMemoryCorpusStore(),
            completion=completion,
            clock=FakeClock(),
            ids=SequentialIds(),
        )
    assert completion.calls == []


# --- Accepting (the design-signature rule) ---


def test_accept_diff_item_with_accepted_at_is_a_batch_referencing_it() -> None:
    """Given an item with accepted_at set, When accepted, Then a batch exists
    referencing that item; with accepted_at unset it raises."""
    batch = accept_diff_item(
        make_diff_item(accepted_at=5),
        DiffKind.REBUILD,
        make_roots(),
        HostRole.WRITER,
        ids=SequentialIds(),
    )

    assert isinstance(batch, WriteBatch) and batch.diff_item_id == "item-1"
    with pytest.raises(NotAccepted):
        accept_diff_item(
            make_diff_item(),
            DiffKind.REBUILD,
            make_roots(),
            HostRole.WRITER,
            ids=SequentialIds(),
        )


def test_accept_diff_item_on_a_reader_is_not_writer() -> None:
    """Given role reader, When an accepted item is accepted, Then the result is
    NotWriter."""
    result = accept_diff_item(
        make_diff_item(accepted_at=5),
        DiffKind.REBUILD,
        make_roots(),
        HostRole.READER,
        ids=SequentialIds(),
    )

    assert isinstance(result, NotWriter)


# --- Accepting (diff.accept) ---


def test_accept_records_accepted_at_and_offers_one_batch() -> None:
    """Given a proposed item, When accepted twice, Then accepted_at is recorded,
    one PROPOSED batch referencing the item is stored and offered, and the
    repeat returns the same acceptance."""
    writer = Writer((ASYNC_TO_CONCURRENCY,))
    item = writer.propose(DiffKind.REBUILD)
    writer.clock.advance(500)

    accepted = writer.accept(item)
    repeat = writer.accept(item)

    assert isinstance(accepted, DiffItem) and repeat == accepted
    assert accepted.accepted_at == 1_500 and accepted.batch_id is not None
    (record,) = writer.store.list_batches()
    assert record.state is BatchState.PROPOSED and record.profile_id == A
    assert record.batch.diff_item_id == item.item_id
    assert record.batch.batch_id == accepted.batch_id
    offers = [
        p.event
        for p in writer.store.unacked_events(A)
        if isinstance(p.event, BatchOffered)
    ]
    assert [o.batch.batch_id for o in offers] == [accepted.batch_id]


def test_accept_on_a_reader_is_not_writer_and_records_nothing() -> None:
    """Given a proposed item, When a reader accepts it, Then the result is
    NotWriter, the item stays unaccepted and no batch row exists."""
    writer = Writer((ASYNC_TO_CONCURRENCY,))
    item = writer.propose(DiffKind.REBUILD)

    result = writer.accept(item, HostRole.READER)

    assert isinstance(result, NotWriter)
    assert writer.store.get_diff_item(item.item_id) == item
    assert writer.store.list_batches() == []


def test_accept_of_an_unknown_item_is_not_found() -> None:
    """Given no such item, When accepted, Then it is an unknown record."""
    with pytest.raises(UnknownRecord):
        Writer().accept(make_diff_item("item-404"))


def test_accept_after_the_folder_was_locked_is_refused() -> None:
    """Given an item moving a folder that the user locked after the proposal,
    When accepted, Then it is refused and nothing is recorded (locked is never
    moved by any batch)."""
    writer = Writer((ASYNC_TO_CONCURRENCY,))
    item = writer.propose(DiffKind.REBUILD)
    writer.store.put_folder_flags(NodeId("16"), FolderFlags(pinned=False, locked=True))

    with pytest.raises(InvalidRequest):
        writer.accept(item)
    assert writer.store.list_batches() == []


def test_an_audit_item_crosses_the_boundary_and_its_undo_carries_the_item() -> None:
    """Given an accepted audit item moving a Dynomark folder into the user's bar,
    When its batch is applied and then undone, Then the batch was admitted and
    the inverse carries the same item reference."""
    writer = Writer((ASYNC_TO_READING,))
    item = writer.propose(DiffKind.AUDIT)
    accepted = writer.accept(item)
    assert isinstance(accepted, DiffItem) and accepted.batch_id is not None
    after = make_tree(
        *(n for n in TREE.nodes[3:] if n.node_id != "16"),
        make_node("16", "30", "Async"),
        taken_at=TREE.taken_at + 1,
    )
    receive_receipt(
        ReceiptApplied(
            batch_id=accepted.batch_id,
            applied=(OpApplied(index=0, node_id=NodeId("16"), changed=True),),
            skipped=(),
            pre_batch=True,
            snapshot=TREE,
        ),
        make_roots(),
        store=writer.store,
        clock=writer.clock,
        ids=writer.ids,
    )
    record_tree_snapshot(after, HostRole.WRITER, store=writer.store)

    undone = undo(
        accepted.batch_id,
        HostRole.WRITER,
        make_roots(),
        store=writer.store,
        clock=writer.clock,
        ids=writer.ids,
    )

    assert isinstance(undone, Undone) and undone.batch is not None
    assert undone.batch.diff_item_id == item.item_id
    assert undone.batch.operations[0] == OpMove(
        index=0,
        node_id=NodeId("16"),
        to=RUST,
        expect=Expect(parent_id=NodeId("30"), parent_path=READING),
    )


# --- Reading diffs ---


def test_diff_items_page_shows_the_batch_and_state_of_an_accepted_item() -> None:
    """Given an accepted item, When its diff's page is read, Then the item
    carries accepted_at, its batch id and the batch's state."""
    writer = Writer((ASYNC_TO_CONCURRENCY,))
    item = writer.propose(DiffKind.REBUILD)
    writer.accept(item)

    diff, page = diff_items_page(item.diff_id, None, 100, store=writer.store)

    (view,) = page.items
    assert diff.diff_id == item.diff_id and page.next_cursor is None
    assert view.item.accepted_at is not None
    assert view.batch_state is BatchState.PROPOSED


def test_diff_items_page_of_an_unknown_diff_is_not_found() -> None:
    """Given no such diff, When its page is read, Then it is an unknown record."""
    with pytest.raises(UnknownRecord):
        diff_items_page(DiffId("diff-404"), None, 100, store=InMemoryCorpusStore())


def test_diffs_are_listed_newest_first() -> None:
    """Given two proposed diffs, When listed, Then the newer comes first."""
    writer = Writer((ASYNC_TO_CONCURRENCY,), (ASYNC_TO_READING,))
    first = writer.propose(DiffKind.REBUILD, "req-1")
    writer.clock.advance(1)
    second = writer.propose(DiffKind.AUDIT, "req-2")

    page = list_diffs_page(None, 100, store=writer.store)

    assert [d.diff_id for d in page.items] == [second.diff_id, first.diff_id]
