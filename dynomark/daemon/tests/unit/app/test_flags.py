"""Pin and lock an owned folder (DYNOMARK.DESIGN.md, glossary ``pinned`` and
``locked``; Behaviors "Placement respects a lock"; contract/v2
``folder.flags.set``: addressed by path -- flags are keyed by FolderPath,
which every writer's tree resolves alike (issue #423) -- only the flags
given change, idempotent on (path, flag values); a folder outside the owned
roots is ``invalid``, a path that resolves to no folder ``not_found``;
``not_writer`` on a reader).
"""

import pytest

from dynomark_daemon.app.errors import InvalidRequest, TreeNotReady, UnknownRecord
from dynomark_daemon.app.flags import locked_folders, set_folder_flags
from dynomark_daemon.app.run import current_outline
from dynomark_daemon.domain.ids import NodeId
from dynomark_daemon.domain.roles import HostRole, NotWriter
from dynomark_daemon.domain.tree import FolderPath, OutlineFolder
from dynomark_daemon.domain.writer import WriterConflict
from dynomark_daemon.testing.store import InMemoryCorpusStore
from tests._factories import make_node, make_path, make_roots, make_tree

RUST = make_path("Dynomark", "Rust")
TREE = make_tree(
    make_node("10", "1", "Follow Up"),
    make_node("11", "1", "Dynomark", index=1),
    make_node("30", "1", "Reading", index=2),
    make_node("14", "11", "Rust"),
    make_node("40", "14", "Tokio", url="https://tokio.rs/"),
)


def _store() -> InMemoryCorpusStore:
    store = InMemoryCorpusStore()
    store.put_tree_snapshot(TREE)
    return store


def _set(
    store: InMemoryCorpusStore,
    path: FolderPath = RUST,
    *,
    pinned: bool | None = None,
    locked: bool | None = None,
    role: HostRole = HostRole.WRITER,
) -> OutlineFolder | NotWriter | WriterConflict:
    return set_folder_flags(path, pinned, locked, role, make_roots(), store=store)


def test_locking_a_folder_keeps_its_pin_and_shows_in_the_outline() -> None:
    """Given a pinned owned folder, When it is locked, Then the answer holds both
    flags and its bookmark count, and the outline placement reads is locked."""
    store = _store()
    _set(store, pinned=True)

    folder = _set(store, RUST, locked=True)

    assert folder == OutlineFolder(NodeId("14"), RUST, True, True, 1)
    outline = current_outline(make_roots(), store=store)
    assert outline.is_locked(make_path("Dynomark", "Rust", "Async"))


def test_setting_the_same_flags_again_changes_nothing() -> None:
    """Given a locked folder, When locked again, Then the answer is the same."""
    store = _store()
    first = _set(store, locked=True)

    assert _set(store, locked=True) == first


@pytest.mark.parametrize(
    "path",
    [make_path("Dynomark", "Go"), make_path("Dynomark", "Rust", "Tokio")],
    ids=["no-such-folder", "a-bookmark-title"],
)
def test_a_path_that_resolves_to_no_folder_is_not_found(path: FolderPath) -> None:
    """Given the tree, When flags name a path no folder of it resolves to (none
    there, or only a bookmark of that title), Then it is an unknown record."""
    with pytest.raises(UnknownRecord):
        _set(_store(), path, locked=True)


def test_a_folder_is_found_by_path_whatever_its_node_id() -> None:
    """Given a writer whose tree holds Dynomark/Rust under node 99 (another
    writer's numbering), When Rust is locked by path, Then the answer names
    this tree's node and the lock is kept by path (issue #423)."""
    store = InMemoryCorpusStore()
    store.put_tree_snapshot(
        make_tree(
            make_node("70", "1", "Follow Up"),
            make_node("71", "1", "Dynomark", index=1),
            make_node("99", "71", "Rust"),
        )
    )

    folder = _set(store, RUST, locked=True)

    assert isinstance(folder, OutlineFolder) and folder.node_id == "99"
    assert store.folder_flags()[RUST].locked


def test_a_folder_outside_the_owned_roots_is_invalid() -> None:
    """Given the user's own Reading folder, When it is pinned, Then the request
    is one the daemon cannot act on."""
    with pytest.raises(InvalidRequest):
        _set(_store(), make_path("Reading"), pinned=True)


def test_flags_before_any_tree_snapshot_are_not_ready() -> None:
    """Given no tree snapshot, When flags are set, Then it is not ready (busy)."""
    with pytest.raises(TreeNotReady):
        _set(InMemoryCorpusStore(), locked=True)


def test_a_reader_sets_no_flags() -> None:
    """Given role reader, When flags are set, Then the result is NotWriter and
    nothing is stored."""
    store = _store()

    assert isinstance(_set(store, locked=True, role=HostRole.READER), NotWriter)
    assert store.folder_flags() == {}


def test_a_lock_is_kept_by_folder_path_across_a_writer_change() -> None:
    """Given a folder locked on one writer, When another writer's tree holds
    the same folder under another node id, Then the outline and the folders
    no batch may move still show it locked: flags are keyed by folder path,
    stable across writers, not by a host's node id (issue #423)."""
    store = _store()
    _set(store, locked=True)
    renumbered = make_tree(
        make_node("70", "1", "Follow Up"),
        make_node("71", "1", "Dynomark", index=1),
        make_node("99", "71", "Rust"),
        taken_at=TREE.taken_at + 1,
    )
    store.put_tree_snapshot(renumbered)

    outline = current_outline(make_roots(), store=store)

    folder = outline.folder_at(RUST)
    assert folder is not None and (folder.node_id, folder.locked) == ("99", True)
    assert locked_folders(renumbered, store=store) == {NodeId("99")}
