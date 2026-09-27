"""Use cases: a diff is proposed; a diff item is accepted (DYNOMARK.DESIGN.md,
Behaviors and Interfaces; The daemon, "Diffs"; Goal 8; contract/v1
``diff.propose``, ``diff.list``, ``diff.page``, ``diff.accept``).

Nothing is applied until an item is accepted, and each acceptance is its
own batch. Merge rules stay undefined (design Open Question 1): whatever
the completion proposes is kept only if it keeps the domain's rules.
"""

import hashlib
import json
from dataclasses import dataclass, replace

from dynomark_daemon.app.errors import (
    InvalidRequest,
    TreeNotReady,
    UnknownRecord,
)
from dynomark_daemon.app.file import offer
from dynomark_daemon.app.pages import Page, paginate
from dynomark_daemon.app.requests import RequestRecall, recall_request
from dynomark_daemon.app.run import current_outline
from dynomark_daemon.domain.batch import (
    BatchRecord,
    BatchState,
    OutsideOwnedRoots,
    WriteBatch,
)
from dynomark_daemon.domain.diff import (
    DiffItem,
    DiffKind,
    DiffScope,
    NotAccepted,
    TreeDiff,
    item_batch,
    vet,
    violations,
)
from dynomark_daemon.domain.events import DiffProposed
from dynomark_daemon.domain.ids import (
    DiffId,
    EventId,
    HostId,
    ItemId,
    ProfileId,
    RequestId,
)
from dynomark_daemon.domain.roles import HostRole, NotWriter
from dynomark_daemon.domain.tree import OwnedRoots, TreeOutline, bar_outline
from dynomark_daemon.domain.writer import WriterConflict, writer_standing
from dynomark_daemon.ports.clock import Clock, IdSource
from dynomark_daemon.ports.completion import CompletionPort
from dynomark_daemon.ports.store import CorpusStorePort


@dataclass(frozen=True, slots=True)
class ItemView:
    """A diff item as ``diff.page`` shows it: with its batch's state once
    accepted."""

    item: DiffItem
    batch_state: BatchState | None


# --- Proposing ---


def diff_scope(
    kind: DiffKind, roots: OwnedRoots, *, store: CorpusStorePort
) -> DiffScope:
    """The outlines a diff of ``kind`` is proposed from and checked against.

    Raises:
        TreeNotReady: no tree snapshot yet.
    """
    tree = store.latest_tree_snapshot()
    if tree is None:
        raise TreeNotReady("no tree snapshot to propose a diff from")
    return DiffScope(
        kind=kind,
        outline=current_outline(roots, store=store),
        own_bar=bar_outline(tree, roots, store.folder_flags()),
        roots=roots,
    )


def propose_diff(
    kind: DiffKind,
    outline: TreeOutline,
    own_bar: TreeOutline,
    roots: OwnedRoots,
    *,
    completion: CompletionPort,
    clock: Clock,
    ids: IdSource,
) -> TreeDiff:
    """A diff of ``kind`` between the ``Dynomark`` outline and the user's own
    bar: the completion's proposals that keep the rules, each an unaccepted
    item. No batch exists.

    Raises:
        CompletionError: the completion could not propose.
    """
    scope = DiffScope(kind=kind, outline=outline, own_bar=own_bar, roots=roots)
    proposals = completion.propose_diff(kind, outline=outline, own_bar=own_bar)
    kept = [p for p in (vet(proposal, scope) for proposal in proposals) if p]
    diff_id = DiffId(ids.new_id("diff"))
    items = tuple(
        DiffItem(
            item_id=ItemId(ids.new_id("item")),
            diff_id=diff_id,
            action=proposal.action,
            description=proposal.description,
            operations=proposal.operations,
        )
        for proposal in kept
    )
    return TreeDiff(diff_id=diff_id, kind=kind, proposed_at=clock.now_ms(), items=items)


def _request_diff_id(request_id: RequestId) -> DiffId:
    """The diff a ``diff.propose`` request id names, for as long as it is kept
    (a retry with the same id returns the same diff)."""
    digest = hashlib.sha256(request_id.encode("utf-8")).hexdigest()[:40]
    return DiffId(f"diff-{digest}")


def request_diff(
    request_id: RequestId,
    kind: DiffKind,
    role: HostRole,
    roots: OwnedRoots,
    *,
    store: CorpusStorePort,
    completion: CompletionPort,
    clock: Clock,
    ids: IdSource,
) -> TreeDiff:
    """The diff ``diff.propose`` asked for, proposed and stored once per
    request id.

    Raises:
        InvalidRequest: the id is known with another body, or this host is a
            reader (it keeps no tree to propose from).
        TreeNotReady: no tree snapshot yet (``busy``).
        CompletionError: the completion could not propose.
    """
    if role is HostRole.READER:
        raise InvalidRequest("a reader keeps no tree to propose a diff from")
    body = json.dumps({"type": "diff.propose", "kind": kind.value}, sort_keys=True)
    recall = recall_request(request_id, body, store=store)
    diff_id = _request_diff_id(request_id)
    known = store.get_diff(diff_id)
    if recall is RequestRecall.REPEAT and known is not None:
        return known
    scope = diff_scope(kind, roots, store=store)
    diff = propose_diff(
        kind,
        scope.outline,
        scope.own_bar,
        roots,
        completion=completion,
        clock=clock,
        ids=ids,
    ).with_id(diff_id)
    store.put_diff(diff)
    return diff


def propose_scheduled_rebuild(
    cadence_ms: int | None,
    role: HostRole,
    host_id: HostId,
    roots: OwnedRoots,
    *,
    store: CorpusStorePort,
    completion: CompletionPort,
    clock: Clock,
    ids: IdSource,
) -> TreeDiff | None:
    """A rebuild the daemon proposes on its own once ``cadence_ms`` has passed
    since the last one (Config rebuild cadence), stored and announced to the
    writer's profile by a ``diff.proposed`` event; ``None`` when none is due
    (manual only, a reader, no bound profile or tree, or a writer conflict).

    Raises:
        CompletionError: the completion could not propose.
    """
    profile = store.writer_profile()
    tree = store.latest_tree_snapshot()
    if cadence_ms is None or role is HostRole.READER or profile is None or not tree:
        return None
    if writer_standing(tree, roots, host_id, role).conflict:
        return None
    now = clock.now_ms()
    last = max(
        (d.proposed_at for d in store.list_diffs() if d.kind is DiffKind.REBUILD),
        default=None,
    )
    if last is not None and now - last < cadence_ms:
        return None
    scope = diff_scope(DiffKind.REBUILD, roots, store=store)
    diff = propose_diff(
        DiffKind.REBUILD,
        scope.outline,
        scope.own_bar,
        roots,
        completion=completion,
        clock=clock,
        ids=ids,
    )
    store.put_diff(diff)
    event = DiffProposed(event_id=EventId(ids.new_id("event")), diff=diff)
    store.put_event(profile, event)
    return diff


# --- Accepting ---


def accept_diff_item(
    item: DiffItem, kind: DiffKind, roots: OwnedRoots, role: HostRole
) -> WriteBatch | NotWriter:
    """The batch an accepted item becomes, referencing it.

    Raises:
        NotAccepted: ``accepted_at`` is unset (before a batch exists).
        OutsideOwnedRoots: a rebuild item leaves the owned roots.
    """
    if role is HostRole.READER:
        return NotWriter(use_case="accept_diff_item")
    return item_batch(item, kind, roots)


def accept_diff(
    item_id: ItemId,
    role: HostRole,
    roots: OwnedRoots,
    profile_id: ProfileId,
    *,
    conflict: WriterConflict | None = None,
    store: CorpusStorePort,
    clock: Clock,
    ids: IdSource,
) -> DiffItem | NotWriter | WriterConflict:
    """Record the acceptance of one item and offer its batch, once; a repeat
    returns the recorded acceptance (and offers the batch if it was lost).
    A writer in ``conflict`` refuses.

    Raises:
        UnknownRecord: no such item (``not_found``).
        InvalidRequest: the item no longer keeps the rules against the
            current tree -- a folder since locked or pinned (``invalid``).
        TreeNotReady: no tree snapshot yet (``busy``).
    """
    if role is HostRole.READER:
        return NotWriter(use_case="accept_diff_item")
    if conflict is not None:
        return conflict
    item = store.get_diff_item(item_id)
    diff = None if item is None else store.get_diff(item.diff_id)
    if item is None or diff is None:
        raise UnknownRecord(f"no diff item {item_id}")
    if item.accepted_at is None:
        scope = diff_scope(diff.kind, roots, store=store)
        broken = violations(item.operations, scope)
        if broken:
            raise InvalidRequest(f"item {item_id} no longer applies: {broken[0]}")
        item = replace(item, accepted_at=clock.now_ms())
    try:
        batch = accept_diff_item(item, diff.kind, roots, role)
    except (NotAccepted, OutsideOwnedRoots) as error:
        raise InvalidRequest(str(error)) from error
    if isinstance(batch, NotWriter):
        return batch
    if store.get_batch(batch.batch_id) is None:
        record = BatchRecord(
            batch=batch,
            state=BatchState.PROPOSED,
            created_at=clock.now_ms(),
            profile_id=profile_id,
        )
        offer(record, store=store, ids=ids)
    accepted = replace(item, batch_id=batch.batch_id)
    if accepted != store.get_diff_item(item_id):
        store.put_diff_item(accepted)
    return accepted


# --- Reading ---


def list_diffs_page(
    cursor: str | None, limit: int, *, store: CorpusStorePort
) -> Page[TreeDiff]:
    """One page of diffs, newest first (``diff.list``).

    Raises:
        StaleCursor: the cursor is not one of this list.
    """
    return paginate(
        store.list_diffs(),
        lambda diff: diff.diff_id,
        kind="diff",
        params="",
        cursor=cursor,
        limit=limit,
    )


def diff_items_page(
    diff_id: DiffId, cursor: str | None, limit: int, *, store: CorpusStorePort
) -> tuple[TreeDiff, Page[ItemView]]:
    """The diff and one page of its items, each accepted one with its batch's
    current state (``diff.page``).

    Raises:
        UnknownRecord: no such diff (``not_found``).
        StaleCursor: the cursor is not one of this diff's pages.
    """
    diff = store.get_diff(diff_id)
    if diff is None:
        raise UnknownRecord(f"no diff {diff_id}")
    views = []
    for item in diff.items:
        record = None if item.batch_id is None else store.get_batch(item.batch_id)
        views.append(ItemView(item, None if record is None else record.state))
    page = paginate(
        views,
        lambda view: view.item.item_id,
        kind="diff.page",
        params=diff_id,
        cursor=cursor,
        limit=limit,
    )
    return diff, page
