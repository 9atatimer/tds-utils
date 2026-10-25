"""application/load.py -- load_declaration: read the Declaration at a target.

ARCHITECTURE.ARCH-ADHERENCE.md, Use-case surface. The caller passes a
DeclarationUnreadable through; measure is its one owner (task-058).
"""

from __future__ import annotations

from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import (
    DECLARATION_PATH,
    Declaration,
    DeclarationUnreadable,
    parse_declaration,
)
from adherence.domain.target import Base, Head
from adherence.ports.repository import Absent, Refused, RepositoryPort


def load_declaration(
    at: Base | Head, *, repository: RepositoryPort, deadline: Deadline | None
) -> Declaration | DeclarationUnreadable:
    """The Declaration adherence.toml states at the target.

    Declaration.none when the target has no adherence.toml;
    DeclarationUnreadable, naming why, when it cannot be read or parsed.
    """
    text = repository.read(DECLARATION_PATH, at, deadline)
    if isinstance(text, Absent):
        return Declaration.none
    if isinstance(text, Refused):
        return DeclarationUnreadable(f"{DECLARATION_PATH} refused: {text.reason}")
    if isinstance(text, TimedOut):
        return DeclarationUnreadable(f"{text.operation}: timed out")
    return parse_declaration(text)
