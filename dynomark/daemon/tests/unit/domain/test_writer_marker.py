"""The writer marker (DYNOMARK.DESIGN.md, Key Decisions "Two writers", MVP
half: "refuse on a writer marker in the owned tree"; contract/v1 README,
Writer marker: an empty folder titled exactly ``dynomark-writer:<host_id>``
directly in ``owned_roots.dynomark``, created by an ordinary batch; marker
folders are excluded from the outline and from placement).
"""

from dynomark_daemon.domain.batch import OpCreateFolder
from dynomark_daemon.domain.ids import HostId
from dynomark_daemon.domain.placement import admit_folder
from dynomark_daemon.domain.roles import HostRole
from dynomark_daemon.domain.tree import FolderPath, RootKey
from dynomark_daemon.domain.writer import (
    WriterConflict,
    marker_operations,
    marker_title,
    markers_in,
    writer_standing,
)
from tests._factories import (
    make_node,
    make_outline,
    make_outline_folder,
    make_path,
    make_roots,
    make_tree,
)

MBP = HostId("mbp")
TREE = make_tree(
    make_node("11", "1", "Dynomark"),
    make_node("14", "11", "Rust"),
    make_node("15", "11", "dynomark-writer:mbp", index=1),
    make_node("16", "11", "dynomark-writer:work-laptop", index=2),
    make_node("17", "14", "dynomark-writer:nested"),
    make_node("18", "11", "dynomark-writer:bad id!", index=3),
    make_node("19", "11", "dynomark-writer:bm", index=4, url="https://x.example/"),
)


def test_markers_are_the_valid_marker_folders_directly_in_dynomark() -> None:
    """Given marker-titled folders in and below Dynomark, one with an invalid
    host id and a bookmark with a marker title, When markers are read, Then
    only the folders directly in Dynomark with a valid host id count."""
    assert markers_in(TREE, make_roots()) == (MBP, HostId("work-laptop"))


def test_a_writer_seeing_another_hosts_marker_is_in_conflict() -> None:
    """Given the tree holds this host's and another host's marker, When a
    writer reads its standing, Then it has its own marker, names the other,
    and is in conflict; a reader never is."""
    writer = writer_standing(TREE, make_roots(), MBP, HostRole.WRITER)
    reader = writer_standing(TREE, make_roots(), MBP, HostRole.READER)

    assert (writer.own_marker, writer.other_writers, writer.conflict) == (
        True,
        (HostId("work-laptop"),),
        True,
    )
    assert not reader.conflict


def test_no_tree_means_no_marker_and_no_conflict() -> None:
    """Given no tree snapshot yet, When a writer reads its standing, Then it has
    no marker and is not in conflict."""
    standing = writer_standing(None, make_roots(), MBP, HostRole.WRITER)

    assert (standing.own_marker, standing.other_writers, standing.conflict) == (
        False,
        (),
        False,
    )


def test_the_conflict_names_the_other_host() -> None:
    """Given a conflict with work-laptop, When its reason is read, Then it names
    the code and the other host (the job's last_error)."""
    conflict = WriterConflict(other_writers=(HostId("work-laptop"),))

    assert conflict.reason() == "writer_conflict: marker of host work-laptop present"


def test_the_marker_batch_creates_dynomark_then_the_marker() -> None:
    """Given the owned roots, When the marker operations are built, Then they
    create Dynomark in the bar and the marker folder directly in it
    (batch.offer--writer-marker.json)."""
    bar = FolderPath(root=RootKey.BAR, names=())

    assert marker_title(MBP) == "dynomark-writer:mbp"
    assert marker_operations(make_roots(), MBP) == (
        OpCreateFolder(index=0, parent=bar, title="Dynomark"),
        OpCreateFolder(index=1, parent=make_path("Dynomark"), title=marker_title(MBP)),
    )


def test_placement_never_files_into_a_marker_named_leaf() -> None:
    """Given a completion proposing a new leaf titled like a marker, When the
    folder is admitted, Then the entry goes to its neighbours' folder."""
    outline = make_outline(make_outline_folder("Dynomark", "Rust"))
    choice = make_path("Dynomark", "dynomark-writer:evil")

    folder = admit_folder(choice, outline, [make_path("Dynomark", "Rust")])

    assert folder == make_path("Dynomark", "Rust")
