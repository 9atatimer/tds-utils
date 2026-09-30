"""Pin and lock an owned folder (DYNOMARK.DESIGN.md, glossary ``pinned`` and
``locked``; Behaviors "Placement respects a lock"; contract/v1
``folder.flags.set``: addressed by node id, ``path`` a check, only the
flags given change, idempotent on (node_id, flag values); a folder outside
the owned roots is ``invalid``, an unknown node or a path mismatch
``not_found``; ``not_writer`` on a reader).
"""

import pytest

from dynomark_daemon.app.errors import InvalidRequest, TreeNotReady, UnknownRecord
from dynomark_daemon.app.flags import set_folder_flags
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
    node_id: str = "14",
    *,
    path: FolderPath | None = None,
    pinned: bool | None = None,
    locked: bool | None = None,
    role: HostRole = HostRole.WRITER,
) -> OutlineFolder | NotWriter | WriterConflict:
    return set_folder_flags(
        NodeId(node_id), path, pinned, locked, role, make_roots(), store=store
    )


def test_locking_a_folder_keeps_its_pin_and_shows_in_the_outline() -> None:
    """Given a pinned owned folder, When it is locked, Then the answer holds both
    flags and its bookmark count, and the outline placement reads is locked."""
    store = _store()
    _set(store, pinned=True)

    folder = _set(store, path=RUST, locked=True)

    assert folder == OutlineFolder(NodeId("14"), RUST, True, True, 1)
    outline = current_outline(make_roots(), store=store)
    assert outline.is_locked(make_path("Dynomark", "Rust", "Async"))


def test_setting_the_same_flags_again_changes_nothing() -> None:
    """Given a locked folder, When locked again, Then the answer is the same."""
    store = _store()
    first = _set(store, locked=True)

    assert _set(store, locked=True) == first


@pytest.mark.parametrize(
    ("node_id", "path"),
    [("99", None), ("40", None), ("14", make_path("Dynomark", "Go"))],
    ids=["unknown-node", "a-bookmark", "path-mismatch"],
)
def test_an_unknown_folder_or_a_wrong_path_is_not_found(
    node_id: str, path: FolderPath | None
) -> None:
    """Given the tree, When flags name no folder, a bookmark, or a folder whose
    path differs from the check, Then it is an unknown record."""
    with pytest.raises(UnknownRecord):
        _set(_store(), node_id, path=path, locked=True)


def test_a_folder_outside_the_owned_roots_is_invalid() -> None:
    """Given the user's own Reading folder, When it is pinned, Then the request
    is one the daemon cannot act on."""
    with pytest.raises(InvalidRequest):
        _set(_store(), "30", pinned=True)


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
