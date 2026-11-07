"""The git RepositoryPort adapter: the shared contract, then what only a
real repository can show -- links refused, paths outside the root refused,
and a passed deadline answered with TimedOut (ARCHITECTURE.ARCH-ADHERENCE.md,
Security mitigations). Real git in a throwaway repository under tmp_path.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Collection
from pathlib import Path

import pytest

from adherence.adapters.git import GitRepository
from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.target import Base, Head
from adherence.ports.repository import Refused, RepositoryPort
from tests.git_kit import GIT_ENV, git, make_repository
from tests.repository_contract import Files, RepositoryContract


class TestGitRepository(RepositoryContract):
    def repository_with(
        self,
        tmp_path: Path,
        *,
        base: Files,
        staged: Files,
        working: Files,
        deleted: Collection[str] = (),
    ) -> tuple[RepositoryPort, Base]:
        root = tmp_path / "repo"
        at_base = make_repository(
            root, base=base, staged=staged, working=working, deleted=deleted
        )
        return GitRepository(str(root)), at_base


def _with_link(tmp_path: Path) -> tuple[GitRepository, Base]:
    root = tmp_path / "repo"
    (tmp_path / "secret").write_bytes(b"outside\n")
    git(tmp_path, "init", "-q", "-b", "master", str(root))
    (root / "link").symlink_to(tmp_path / "secret")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "link")
    return GitRepository(str(root)), Base(git(root, "rev-parse", "HEAD"))


def test_read_of_a_symbolic_link_is_refused_in_every_target(tmp_path: Path) -> None:
    """Given a committed, staged and checked-out symbolic link, When it is read
    at each target, Then it is Refused, and the bytes it points at never leave."""
    repository, base = _with_link(tmp_path)

    for at in (base, Head.staged_index(), Head.working_tree()):
        answer = repository.read("link", at, None)
        assert isinstance(answer, Refused), at
        assert "symbolic link" in answer.reason


@pytest.mark.parametrize("path", ["../secret", "/etc/hosts", "a/../../secret"])
def test_read_of_a_path_outside_the_root_is_refused(tmp_path: Path, path: str) -> None:
    """Given a path that resolves outside the repository, When it is read at
    each target, Then it is Refused."""
    repository, base = _with_link(tmp_path)

    for at in (base, Head.staged_index(), Head.working_tree()):
        answer = repository.read(path, at, None)
        assert isinstance(answer, Refused), (path, at)


def test_read_and_tree_past_the_deadline_time_out(tmp_path: Path) -> None:
    """Given a deadline already passed, When the repository is read or listed,
    Then it answers TimedOut rather than overrun."""
    root = tmp_path / "repo"
    base = make_repository(root, base={"a": b"a\n"}, staged={}, working={})
    repository = GitRepository(str(root))
    passed = Deadline(epoch_seconds=0.0)

    for at in (base, Head.staged_index(), Head.working_tree()):
        assert isinstance(repository.read("a", at, passed), TimedOut)
        assert isinstance(repository.tree(at, passed), TimedOut)


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode-000 file")
def test_read_of_a_file_that_cannot_be_opened_is_refused(tmp_path: Path) -> None:
    """Given a working-tree file the process may not open, When it is read,
    Then it is Refused naming why, never an exception."""
    root = tmp_path / "repo"
    make_repository(root, base={"a": b"a\n"}, staged={}, working={})
    (root / "a").chmod(0)
    try:
        answer = GitRepository(str(root)).read("a", Head.working_tree(), None)
    finally:
        (root / "a").chmod(0o644)

    assert isinstance(answer, Refused)
    assert "permission" in answer.reason.lower()


def test_read_of_a_directory_is_refused_not_absent(tmp_path: Path) -> None:
    """Given a directory where a file is asked for, When it is read in the
    working tree, Then it is Refused, so a present declaration is never
    mistaken for no declaration."""
    root = tmp_path / "repo"
    make_repository(root, base={"a": b"a\n"}, staged={}, working={})
    (root / "adherence.toml").mkdir()

    answer = GitRepository(str(root)).read("adherence.toml", Head.working_tree(), None)

    assert isinstance(answer, Refused)


def test_read_at_an_unknown_revision_is_refused(tmp_path: Path) -> None:
    """Given a revision the repository does not have, When a file is read at
    it, Then it is Refused naming git's complaint, never an exception."""
    root = tmp_path / "repo"
    make_repository(root, base={"a": b"a\n"}, staged={}, working={})

    answer = GitRepository(str(root)).read("a", Base("f" * 40), None)

    assert isinstance(answer, Refused)
    assert answer.reason


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode-000 directory")
def test_read_under_a_directory_that_cannot_be_opened_is_refused(
    tmp_path: Path,
) -> None:
    """Given a working-tree file under a directory the process may not open,
    When it is read, Then it is Refused naming why, never an exception."""
    root = tmp_path / "repo"
    make_repository(root, base={"pkg/a.py": b"a\n"}, staged={}, working={})
    (root / "pkg").chmod(0)
    try:
        answer = GitRepository(str(root)).read("pkg/a.py", Head.working_tree(), None)
    finally:
        (root / "pkg").chmod(0o755)

    assert isinstance(answer, Refused)
    assert "permission" in answer.reason.lower()


def test_tree_of_a_root_git_cannot_list_is_refused(tmp_path: Path) -> None:
    """Given a root that is no git repository, and a revision the repository
    lacks, When the tree is listed, Then the answer is Refused with git's
    reason, never an exception."""
    plain = tmp_path / "plain"
    plain.mkdir()
    root = tmp_path / "repo"
    make_repository(root, base={"a.py": b"a\n"}, staged={}, working={})

    unlisted = GitRepository(str(plain)).tree(Head.working_tree(), None)
    unknown = GitRepository(str(root)).tree(Base("0" * 40), None)

    assert isinstance(unlisted, Refused) and unlisted.reason
    assert isinstance(unknown, Refused) and unknown.reason


def test_history_lists_newest_first_and_stops_at_the_base(tmp_path: Path) -> None:
    """Given three commits, two of which change adherence.toml, When its
    history at the second commit is asked for, Then it lists only the
    commits on that history that changed it, newest first."""
    root = tmp_path / "repo"
    first = make_repository(
        root, base={"adherence.toml": b"a\n"}, staged={}, working={}
    )
    (root / "other.py").write_bytes(b"x\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "other")
    (root / "adherence.toml").write_bytes(b"b\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "edit")
    second = git(root, "rev-parse", "HEAD")
    (root / "adherence.toml").write_bytes(b"c\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "later")

    history = GitRepository(str(root)).history("adherence.toml", Base(second), None)

    assert history == (second, first.revision)


def test_touched_names_a_declaration_since_deleted(tmp_path: Path) -> None:
    """Given a history that adds a sub-project's adherence.toml and then
    deletes it, When the declarations the base's history touched are asked
    for, Then the deleted one is listed beside the one still present, and
    a file whose name only ends the same way is not."""
    root = tmp_path / "repo"
    make_repository(
        root,
        base={
            "adherence.toml": b"a\n",
            "pkg/adherence.toml": b"b\n",
            "x-adherence.toml": b"c\n",
        },
        staged={},
        working={},
    )
    git(root, "rm", "-q", "pkg/adherence.toml")
    git(root, "commit", "-q", "-m", "drop")
    base = Base(git(root, "rev-parse", "HEAD"))

    repository = GitRepository(str(root))

    assert repository.touched("adherence.toml", base, None) == (
        "adherence.toml",
        "pkg/adherence.toml",
    )
    assert repository.find("adherence.toml", base, None) == ("adherence.toml",)


def test_changed_staged_reads_the_index_git_names_for_its_hook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Given a commit that stages through a temporary index -- `git commit
    -a` or `git commit <paths>` runs its hook with GIT_INDEX_FILE naming it
    -- When the staged change is asked for with that variable set, Then it
    is the temporary index's: b.py is created; and without the variable it
    is the repository's own index, which stages nothing."""
    root = tmp_path / "repo"
    base = make_repository(
        root, base={"a.py": b"x = 1\n"}, staged={}, working={"b.py": b"y = 2\n"}
    )
    index = tmp_path / "next-index"
    index.write_bytes((root / ".git" / "index").read_bytes())
    subprocess.run(
        ["git", "-C", str(root), "add", "b.py"],
        check=True,
        capture_output=True,
        env={**GIT_ENV, "GIT_INDEX_FILE": str(index)},
    )
    monkeypatch.delenv("GIT_INDEX_FILE", raising=False)

    unset = GitRepository(str(root)).changed(base, Head.staged_index(), None)
    monkeypatch.setenv("GIT_INDEX_FILE", str(index))
    named = GitRepository(str(root)).changed(base, Head.staged_index(), None)

    assert not isinstance(unset, Refused | TimedOut), unset
    assert unset.created == ()
    assert not isinstance(named, Refused | TimedOut), named
    assert named.created == ("b.py",)
