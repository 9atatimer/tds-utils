"""RepositoryPort's contract, written once and run against every adapter.

A subclass supplies `repository_with`: a repository whose base revision
holds `base`, whose staged index adds `staged` and removes `deleted`, and
whose working tree adds `working` on top of both. It returns the adapter
and the Base.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from pathlib import Path

from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.target import Base, ChangedPaths, Head, Rename
from adherence.ports.repository import Absent, RepositoryPort

Files = Mapping[str, bytes]
# An instant every clock, real or faked, has long passed.
PASSED = Deadline(epoch_seconds=1.0)


class RepositoryContract:
    def repository_with(
        self,
        tmp_path: Path,
        *,
        base: Files,
        staged: Files,
        working: Files,
        deleted: Collection[str] = (),
    ) -> tuple[RepositoryPort, Base]:
        raise NotImplementedError("a contract subclass supplies its adapter")

    def test_read_returns_each_targets_own_bytes(self, tmp_path: Path) -> None:
        """Given a file changed in the index and again in the working tree,
        When it is read at the base, the staged index and the working tree,
        Then each target answers with its own bytes."""
        repository, base = self.repository_with(
            tmp_path,
            base={"src/a.py": b"base\n"},
            staged={"src/a.py": b"staged\n"},
            working={"src/a.py": b"working\n"},
        )

        assert repository.read("src/a.py", base, None) == b"base\n"
        assert repository.read("src/a.py", Head.staged_index(), None) == b"staged\n"
        assert repository.read("src/a.py", Head.working_tree(), None) == b"working\n"
        head = Head.at_revision(base.revision)
        assert repository.read("src/a.py", head, None) == b"base\n"

    def test_read_of_a_missing_path_is_absent(self, tmp_path: Path) -> None:
        """Given a path no target holds, When it is read, Then it is Absent."""
        repository, base = self.repository_with(
            tmp_path, base={"a.txt": b"a\n"}, staged={}, working={}
        )

        for at in (base, Head.staged_index(), Head.working_tree()):
            assert repository.read("nope.txt", at, None) == Absent("nope.txt")

    def test_read_of_a_path_through_a_file_is_absent(self, tmp_path: Path) -> None:
        """Given a path whose parent is a file, not a directory, When it is
        read at any target, Then it is Absent, as a missing path is."""
        repository, base = self.repository_with(
            tmp_path, base={"a.txt": b"a\n"}, staged={}, working={}
        )

        for at in (base, Head.staged_index(), Head.working_tree()):
            assert repository.read("a.txt/inner", at, None) == Absent("a.txt/inner")

    def test_tree_lists_each_targets_files(self, tmp_path: Path) -> None:
        """Given files added in the index and in the working tree, When each
        target's tree is listed, Then it holds exactly the files that target has."""
        repository, base = self.repository_with(
            tmp_path,
            base={"a.py": b"a\n"},
            staged={"pkg/b.py": b"b\n"},
            working={"c.py": b"c\n"},
        )

        assert repository.tree(base, None) == ("a.py",)
        assert repository.tree(Head.staged_index(), None) == ("a.py", "pkg/b.py")
        assert repository.tree(Head.working_tree(), None) == (
            "a.py",
            "c.py",
            "pkg/b.py",
        )

    def test_changed_names_created_deleted_and_modified_paths(
        self, tmp_path: Path
    ) -> None:
        """Given a base, an index that edits one file, adds one and removes
        one, and a working tree that adds another, When each head is told
        against the base, Then each names exactly what it created, deleted
        and modified."""
        repository, base = self.repository_with(
            tmp_path,
            base={"a.py": b"a\n", "gone.py": b"g\n", "same.py": b"s\n"},
            staged={"a.py": b"a2\n", "pkg/new.py": b"n\n"},
            working={"loose.py": b"l\n"},
            deleted=("gone.py",),
        )

        assert repository.changed(base, Head.staged_index(), None) == ChangedPaths(
            created=("pkg/new.py",), deleted=("gone.py",), modified=("a.py",)
        )
        assert repository.changed(base, Head.working_tree(), None) == ChangedPaths(
            created=("loose.py", "pkg/new.py"), deleted=("gone.py",), modified=("a.py",)
        )
        assert (
            repository.changed(base, Head.at_revision(base.revision), None)
            == ChangedPaths()
        )

    def test_changed_names_a_moved_file_as_renamed(self, tmp_path: Path) -> None:
        """Given an index that moves a file unedited, When the staged index is
        told against the base, Then the move is one rename, neither a
        creation nor a deletion."""
        moved = b"def tidy():\n    pass\n" * 4
        repository, base = self.repository_with(
            tmp_path,
            base={"src/old.py": moved, "keep.py": b"k\n"},
            staged={"src/new.py": moved},
            working={},
            deleted=("src/old.py",),
        )

        assert repository.changed(base, Head.staged_index(), None) == ChangedPaths(
            renamed=(Rename("src/old.py", "src/new.py"),)
        )

    def test_history_lists_the_commits_that_changed_a_path(
        self, tmp_path: Path
    ) -> None:
        """Given a base revision that adds a file, When the file's history at
        the base is asked for, Then it is that revision; a path no commit
        changed has none."""
        repository, base = self.repository_with(
            tmp_path, base={"adherence.toml": b"[layers]\n"}, staged={}, working={}
        )

        assert repository.history("adherence.toml", base, None) == (base.revision,)
        assert repository.history("nope.toml", base, None) == ()

    def test_find_lists_every_path_with_the_name(self, tmp_path: Path) -> None:
        """Given declaration files at the root and in sub-projects, one added
        in the index and one in the working tree, When each target is asked
        for every adherence.toml, Then it lists exactly that target's, sorted,
        and never a path whose name only contains it."""
        repository, base = self.repository_with(
            tmp_path,
            base={
                "adherence.toml": b"[layers]\n",
                "pkg/adherence.toml": b"[layers]\n",
                "pkg/x.py": b"x\n",
                "other/adherence.toml.bak": b"\n",
            },
            staged={"new/deep/adherence.toml": b"[layers]\n"},
            working={"loose/adherence.toml": b"[layers]\n"},
        )

        assert repository.find("adherence.toml", base, None) == (
            "adherence.toml",
            "pkg/adherence.toml",
        )
        assert repository.find("adherence.toml", Head.staged_index(), None) == (
            "adherence.toml",
            "new/deep/adherence.toml",
            "pkg/adherence.toml",
        )
        assert repository.find("adherence.toml", Head.working_tree(), None) == (
            "adherence.toml",
            "loose/adherence.toml",
            "new/deep/adherence.toml",
            "pkg/adherence.toml",
        )

    def test_touched_lists_every_path_with_the_name_the_history_changed(
        self, tmp_path: Path
    ) -> None:
        """Given a base whose history adds declaration files, When the paths
        with that name its history changed are asked for, Then each is
        listed, sorted; a name no commit changed has none."""
        repository, base = self.repository_with(
            tmp_path,
            base={"adherence.toml": b"[layers]\n", "pkg/adherence.toml": b"\n"},
            staged={},
            working={},
        )

        assert repository.touched("adherence.toml", base, None) == (
            "adherence.toml",
            "pkg/adherence.toml",
        )
        assert repository.touched("nope.toml", base, None) == ()

    def test_every_method_past_the_deadline_times_out(self, tmp_path: Path) -> None:
        """Given a deadline already passed, When a file is read, a tree
        listed, a change told or a history asked for, at every target, Then
        each answer is TimedOut, never the bytes or the listing."""
        repository, base = self.repository_with(
            tmp_path,
            base={"src/a.py": b"base\n"},
            staged={"src/a.py": b"staged\n"},
            working={"src/a.py": b"working\n"},
        )

        for at in (base, Head.staged_index(), Head.working_tree()):
            assert isinstance(repository.read("src/a.py", at, PASSED), TimedOut), at
            assert isinstance(repository.tree(at, PASSED), TimedOut), at
        changed = repository.changed(base, Head.staged_index(), PASSED)
        assert isinstance(changed, TimedOut)
        assert isinstance(repository.history("src/a.py", base, PASSED), TimedOut)
        for at in (base, Head.staged_index(), Head.working_tree()):
            assert isinstance(repository.find("a.py", at, PASSED), TimedOut), at
        assert isinstance(repository.touched("a.py", base, PASSED), TimedOut)
