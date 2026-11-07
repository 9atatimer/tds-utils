"""application/load.py -- load_declaration: read the Declaration at a target.

ARCHITECTURE.ARCH-ADHERENCE.md, Use-case surface: every adherence.toml at
the revision, each parsed on its own with its paths under its directory,
merged into the governing declarations by domain/declaration. The caller
passes a DeclarationUnreadable through; measure is its one owner.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import (
    DECLARATION_PATH,
    Declaration,
    DeclarationFile,
    DeclarationUnreadable,
    governing_declarations,
    parse_file,
)
from adherence.domain.target import Base, Head
from adherence.ports.repository import Absent, Refused, RepositoryPort


@dataclass(frozen=True, slots=True)
class Loaded:
    """Each declaration file at a target as read, by path, and all of them
    read as one."""

    files: tuple[tuple[str, DeclarationFile | DeclarationUnreadable], ...]
    declaration: Declaration | DeclarationUnreadable


def read_file(
    path: str, at: Base | Head, *, repository: RepositoryPort, deadline: Deadline | None
) -> DeclarationFile | DeclarationUnreadable | None:
    """One declaration file at the target, None where it is absent."""
    text = repository.read(path, at, deadline)
    if isinstance(text, Absent):
        return None
    if isinstance(text, Refused):
        return DeclarationUnreadable(f"{path} refused: {text.reason}")
    if isinstance(text, TimedOut):
        return DeclarationUnreadable(f"{text.operation}: timed out")
    return parse_file(path, text)


def governed_by(
    files: Sequence[DeclarationFile],
    at: Base | Head,
    *,
    repository: RepositoryPort,
    deadline: Deadline | None,
) -> Declaration | DeclarationUnreadable:
    """The files read as one, their layer conflicts judged over the
    target's tree, which is listed only when two or more could conflict."""
    if len(files) < 2:
        return governing_declarations(files, ())
    tree = repository.tree(at, deadline)
    if isinstance(tree, Refused):
        return DeclarationUnreadable(
            f"the tree its layers are judged over cannot be read: {tree.reason}"
        )
    if isinstance(tree, TimedOut):
        return DeclarationUnreadable(f"{tree.operation}: timed out")
    return governing_declarations(files, tree)


def read_declarations(
    at: Base | Head, *, repository: RepositoryPort, deadline: Deadline | None
) -> Loaded:
    """Every adherence.toml at the target as read, and the governing
    declarations they make: Declaration.none when there is none; the first
    file that cannot be read, or the merge's refusal, as
    DeclarationUnreadable."""
    found = repository.find(DECLARATION_PATH, at, deadline)
    if isinstance(found, Refused):
        return Loaded(
            (), DeclarationUnreadable(f"{found.path} refused: {found.reason}")
        )
    if isinstance(found, TimedOut):
        return Loaded((), DeclarationUnreadable(f"{found.operation}: timed out"))
    files: list[tuple[str, DeclarationFile | DeclarationUnreadable]] = []
    for path in found:
        read = read_file(path, at, repository=repository, deadline=deadline)
        if read is not None:
            files.append((path, read))
    unreadable = next(
        (f for _, f in files if isinstance(f, DeclarationUnreadable)), None
    )
    if unreadable is not None:
        return Loaded(tuple(files), unreadable)
    parsed = [f for _, f in files if isinstance(f, DeclarationFile)]
    return Loaded(
        tuple(files),
        governed_by(parsed, at, repository=repository, deadline=deadline),
    )


def load_declaration(
    at: Base | Head, *, repository: RepositoryPort, deadline: Deadline | None
) -> Declaration | DeclarationUnreadable:
    """The governing declarations every adherence.toml at the target states,
    read as one.

    Declaration.none when the target has none; DeclarationUnreadable,
    naming why, when one cannot be read or parsed or they conflict.
    """
    return read_declarations(at, repository=repository, deadline=deadline).declaration
