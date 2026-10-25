"""RepositoryPort's contract, written once and run against every adapter.

A subclass supplies `repository_with`: a repository whose base revision
holds `base`, whose staged index adds `staged`, and whose working tree
adds `working` on top of both. It returns the adapter and the Base.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from adherence.domain.target import Base, Head
from adherence.ports.repository import Absent, RepositoryPort

Files = Mapping[str, bytes]


class RepositoryContract:
    def repository_with(
        self,
        tmp_path: Path,
        *,
        base: Files,
        staged: Files,
        working: Files,
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
