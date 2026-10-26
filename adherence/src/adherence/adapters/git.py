"""adapters/git.py -- RepositoryPort over git.

A revision is read with `git ls-tree` and `git cat-file`, the staged index
with `git ls-files --stage`, the working tree from disk. The code under
measurement is untrusted (ARCHITECTURE.ARCH-ADHERENCE.md, Security
mitigations): a symbolic link in any target, and any path that resolves
outside the root, is Refused; nothing in the repository is run. Each call
compares the Deadline to the clock and answers TimedOut rather than
overrun it.
"""

from __future__ import annotations

import os
import posixpath
import subprocess
import time
from dataclasses import replace
from pathlib import Path

from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.target import Base, ChangedPaths, Head, HeadKind, Rename
from adherence.ports.repository import Absent, Refused

# --- Constants ---------------------------------------------------------------

SYMLINK_MODE = "120000"
BLOB = "blob"
LINK_REFUSAL = "a symbolic link"
OUTSIDE_REFUSAL = "resolves outside the repository"
# Repository configuration that could run a program is switched off.
SAFE_CONFIG = ("-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null")
# A diff names paths only: no external diff driver, no text conversion.
NAME_STATUS = ("diff", "--no-ext-diff", "--no-textconv", "--name-status", "-z")
FIND_RENAMES = ("-M",)
RENAMED = "R"


class _Expired(Exception):
    """The deadline passed before or during a git call."""


class GitFailure(Exception):
    """git could not answer: it exited non-zero or could not be started.

    read and tree each answer it as Refused, with git's complaint.
    """


# --- Predicates --------------------------------------------------------------


def is_inside_root(path: str) -> bool:
    """Whether a repository-relative path stays inside the root."""
    if not path or path.startswith("/"):
        return False
    normal = posixpath.normpath(path)
    return normal != ".." and not normal.startswith("../")


# --- Pure helpers ------------------------------------------------------------


def _remaining(deadline: Deadline | None) -> float | None:
    if deadline is None:
        return None
    left = deadline.epoch_seconds - time.time()
    if left <= 0:
        raise _Expired
    return left


def _decode(record: bytes) -> tuple[list[str], str]:
    meta, _, path = record.decode("utf-8", "surrogateescape").partition("\t")
    return meta.split(), path


def _tree_entries(listing: bytes) -> list[tuple[str, str, str]]:
    """(mode, object id, path) per blob from `git ls-tree -r -z`."""
    found: list[tuple[str, str, str]] = []
    for record in filter(None, listing.split(b"\0")):
        (mode, kind, object_id), path = _decode(record)
        if kind == BLOB:
            found.append((mode, object_id, path))
    return found


def _index_entries(listing: bytes) -> list[tuple[str, str, str]]:
    """(mode, object id, path) per entry from `git ls-files --stage -z`."""
    found: list[tuple[str, str, str]] = []
    for record in filter(None, listing.split(b"\0")):
        (mode, object_id, _stage), path = _decode(record)
        found.append((mode, object_id, path))
    return found


def _name_status(listing: bytes) -> ChangedPaths:
    """The created, deleted, modified and renamed paths of `git diff -M
    --name-status -z`: a status, then its path, or for a rename its old path
    and its new one."""
    fields = [f.decode("utf-8", "surrogateescape") for f in listing.split(b"\0")]
    created: list[str] = []
    deleted: list[str] = []
    modified: list[str] = []
    renamed: list[Rename] = []
    index = 0
    while index + 1 < len(fields) and fields[index]:
        status, path = fields[index], fields[index + 1]
        if status.startswith(RENAMED) and index + 2 < len(fields):
            renamed.append(Rename(path, fields[index + 2]))
            index += 3
            continue
        {"A": created, "D": deleted}.get(status[:1], modified).append(path)
        index += 2
    return ChangedPaths(
        tuple(sorted(created)),
        tuple(sorted(deleted)),
        tuple(sorted(modified)),
        tuple(sorted(renamed, key=lambda r: r.new)),
    )


def _revision(at: Base | Head) -> str:
    """The revision a Base or a revision Head names."""
    if at.revision is None:
        raise ValueError(f"{at} names no revision")
    return at.revision


# --- Adapter -----------------------------------------------------------------


class GitRepository:
    """RepositoryPort over the git repository whose work tree is `root`."""

    def __init__(self, root: str) -> None:
        self._root = Path(root).resolve()

    def _git(self, args: list[str], deadline: Deadline | None) -> bytes:
        try:
            done = subprocess.run(
                [
                    "git",
                    "--literal-pathspecs",
                    *SAFE_CONFIG,
                    "-C",
                    str(self._root),
                    *args,
                ],
                check=True,
                capture_output=True,
                timeout=_remaining(deadline),
                env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C"},
            )
        except subprocess.TimeoutExpired as expired:
            raise _Expired from expired
        except subprocess.CalledProcessError as failed:
            complaint = failed.stderr.decode("utf-8", "replace").strip()
            raise GitFailure(complaint or f"git exited {failed.returncode}") from failed
        except OSError as unstartable:
            raise GitFailure(f"git could not run: {unstartable}") from unstartable
        return done.stdout

    def _listing(
        self, at: Base | Head, deadline: Deadline | None, *pathspec: str
    ) -> list[tuple[str, str, str]]:
        if isinstance(at, Head) and at.kind is HeadKind.STAGED_INDEX:
            return _index_entries(
                self._git(["ls-files", "--stage", "-z", "--", *pathspec], deadline)
            )
        return _tree_entries(
            self._git(
                ["ls-tree", "-r", "-z", "--full-tree", _revision(at), "--", *pathspec],
                deadline,
            )
        )

    def _read_object(
        self, path: str, at: Base | Head, deadline: Deadline | None
    ) -> bytes | Absent | Refused:
        matches = [e for e in self._listing(at, deadline, path) if e[2] == path]
        if not matches:
            return Absent(path)
        mode, object_id, _ = matches[0]
        if mode == SYMLINK_MODE:
            return Refused(path, LINK_REFUSAL)
        return self._git(["cat-file", BLOB, object_id], deadline)

    def _walk_working(self, path: str) -> bytes | Absent | Refused:
        current = self._root
        for part in Path(path).parts:
            current = current / part
            if current.is_symlink():
                return Refused(path, LINK_REFUSAL)
        if not current.resolve().is_relative_to(self._root):
            return Refused(path, OUTSIDE_REFUSAL)
        if not current.exists():
            return Absent(path)
        if not current.is_file():
            return Refused(path, "not a regular file")
        return current.read_bytes()

    def _read_working(self, path: str) -> bytes | Absent | Refused:
        """The working tree's bytes; any directory or file the process may not
        open, anywhere along the path, is Refused."""
        try:
            return self._walk_working(path)
        except OSError as error:
            return Refused(path, error.strerror or str(error))

    def read(
        self, path: str, at: Base | Head, deadline: Deadline | None
    ) -> bytes | Absent | Refused | TimedOut:
        if not is_inside_root(path):
            return Refused(path, OUTSIDE_REFUSAL)
        normal = posixpath.normpath(path)
        try:
            _remaining(deadline)
            if isinstance(at, Head) and at.kind is HeadKind.WORKING_TREE:
                answer = self._read_working(normal)
            else:
                answer = self._read_object(normal, at, deadline)
        except _Expired:
            return TimedOut(f"read {path}")
        except GitFailure as failure:
            return Refused(path, str(failure))
        return answer

    def _untracked(self, deadline: Deadline | None) -> tuple[str, ...]:
        listing = self._git(
            ["ls-files", "-z", "--others", "--exclude-standard"], deadline
        )
        return tuple(
            p for p in listing.decode("utf-8", "surrogateescape").split("\0") if p
        )

    def _diff(self, base: Base, head: Head, deadline: Deadline | None) -> ChangedPaths:
        if head.kind is HeadKind.REVISION:
            against = [base.revision, _revision(head)]
        elif head.kind is HeadKind.STAGED_INDEX:
            against = ["--cached", base.revision]
        else:
            against = [base.revision]
        found = _name_status(
            self._git([*NAME_STATUS, *FIND_RENAMES, *against, "--"], deadline)
        )
        if head.kind is not HeadKind.WORKING_TREE:
            return found
        created = sorted({*found.created, *self._untracked(deadline)})
        return replace(found, created=tuple(created))

    def changed(
        self, base: Base, head: Head, deadline: Deadline | None
    ) -> ChangedPaths | Refused | TimedOut:
        try:
            return self._diff(base, head, deadline)
        except _Expired:
            return TimedOut("tell what the change did")
        except GitFailure as failure:
            return Refused(".", str(failure))

    def history(
        self, path: str, base: Base, deadline: Deadline | None
    ) -> tuple[str, ...] | Refused | TimedOut:
        if not is_inside_root(path):
            return Refused(path, OUTSIDE_REFUSAL)
        try:
            listing = self._git(
                ["log", "--format=%H", base.revision, "--", posixpath.normpath(path)],
                deadline,
            )
        except _Expired:
            return TimedOut(f"list the history of {path}")
        except GitFailure as failure:
            return Refused(path, str(failure))
        return tuple(listing.decode("ascii", "replace").split())

    def tree(
        self, at: Base | Head, deadline: Deadline | None
    ) -> tuple[str, ...] | Refused | TimedOut:
        try:
            if isinstance(at, Head) and at.kind is HeadKind.WORKING_TREE:
                listing = self._git(
                    ["ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                    deadline,
                )
                paths = {
                    p
                    for p in listing.decode("utf-8", "surrogateescape").split("\0")
                    if p and (self._root / p).is_file()
                }
                return tuple(sorted(paths))
            return tuple(sorted({e[2] for e in self._listing(at, deadline)}))
        except _Expired:
            return TimedOut("list the tree")
        except GitFailure as failure:
            return Refused(".", str(failure))
