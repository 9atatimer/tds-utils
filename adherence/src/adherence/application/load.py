"""application/load.py -- load_declaration: read the Declaration at a target.

ARCHITECTURE.ARCH-ADHERENCE.md, Use-case surface: every adherence.toml at
the revision, each parsed on its own with its paths under its directory,
merged into the governing declarations by domain/declaration. The caller
passes a DeclarationUnreadable through; measure is its one owner.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence

from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import (
    DECLARATION_PATH,
    Declaration,
    DeclarationUnreadable,
    depth_first,
    governing_declarations,
    is_test_data,
    parse_file,
)
from adherence.domain.target import Base, Head
from adherence.ports.repository import Absent, Refused, RepositoryPort


def read_file(
    path: str, at: Base | Head, *, repository: RepositoryPort, deadline: Deadline | None
) -> Declaration | DeclarationUnreadable | None:
    """One declaration file at the target, read on its own; None where it
    is absent."""
    text = repository.read(path, at, deadline)
    if isinstance(text, Absent):
        return None
    if isinstance(text, Refused):
        return DeclarationUnreadable(f"{path} refused: {text.reason}")
    if isinstance(text, TimedOut):
        return DeclarationUnreadable(f"{text.operation}: timed out")
    return parse_file(path, text)


def read_as_one(
    files: Sequence[Declaration | DeclarationUnreadable],
    at: Base | Head,
    *,
    repository: RepositoryPort,
    deadline: Deadline | None,
    tree: Collection[str] | None = None,
) -> Declaration | DeclarationUnreadable:
    """The files read as one: the first that cannot be read, or the
    governing declarations, their layer conflicts judged over the target's
    tree -- the one given, else listed, and only when two or more files
    could conflict."""
    read: list[Declaration] = []
    for file in files:
        if isinstance(file, DeclarationUnreadable):
            return file
        read.append(file)
    if len(read) < 2:
        return governing_declarations(read, ())
    if tree is not None:
        return governing_declarations(read, tree)
    listed = tree_of(at, repository=repository, deadline=deadline)
    if isinstance(listed, DeclarationUnreadable):
        return listed
    return governing_declarations(read, listed)


def tree_of(
    at: Base | Head, *, repository: RepositoryPort, deadline: Deadline | None
) -> tuple[str, ...] | DeclarationUnreadable:
    """The target's tree, which layer conflicts are judged over; why the
    declarations cannot be read when it cannot be listed."""
    tree = repository.tree(at, deadline)
    if isinstance(tree, Refused):
        return DeclarationUnreadable(
            f"the tree its layers are judged over cannot be read: {tree.reason}"
        )
    if isinstance(tree, TimedOut):
        return DeclarationUnreadable(f"{tree.operation}: timed out")
    return tree


def read_declarations(
    at: Base | Head, *, repository: RepositoryPort, deadline: Deadline | None
) -> (
    tuple[tuple[str, Declaration | DeclarationUnreadable], ...] | DeclarationUnreadable
):
    """Every adherence.toml at the target, each read on its own, by path,
    root first; a file a declaration above it places in the test layer is
    test data and never read; DeclarationUnreadable when they cannot be
    listed."""
    found = repository.find(DECLARATION_PATH, at, deadline)
    if isinstance(found, Refused):
        return DeclarationUnreadable(f"{found.path} refused: {found.reason}")
    if isinstance(found, TimedOut):
        return DeclarationUnreadable(f"{found.operation}: timed out")
    files: list[tuple[str, Declaration | DeclarationUnreadable]] = []
    for path in depth_first(found):
        above = [f for _, f in files if isinstance(f, Declaration)]
        if is_test_data(path, above):
            continue
        read = read_file(path, at, repository=repository, deadline=deadline)
        if read is not None:
            files.append((path, read))
    return tuple(files)


def load_declaration(
    at: Base | Head, *, repository: RepositoryPort, deadline: Deadline | None
) -> Declaration | DeclarationUnreadable:
    """The governing declarations every adherence.toml at the target states,
    read as one.

    Declaration.none when the target has none; DeclarationUnreadable,
    naming why, when one cannot be read or parsed or they conflict.
    """
    files = read_declarations(at, repository=repository, deadline=deadline)
    if isinstance(files, DeclarationUnreadable):
        return files
    return read_as_one(
        [read for _, read in files], at, repository=repository, deadline=deadline
    )
