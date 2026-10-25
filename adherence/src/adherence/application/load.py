"""application/load.py -- load_declaration: read the Declaration at a target.

ARCHITECTURE.ARCH-ADHERENCE.md, Use-case surface.
"""

from __future__ import annotations

from adherence.domain.deadline import Deadline
from adherence.domain.declaration import (
    DECLARATION_PATH,
    Declaration,
    parse_declaration,
)
from adherence.domain.target import Base, Head
from adherence.ports.repository import Absent, RepositoryPort


def load_declaration(
    at: Base | Head, *, repository: RepositoryPort, deadline: Deadline | None
) -> Declaration:
    """The Declaration adherence.toml states at the target.

    Declaration.none when the target has no adherence.toml.
    """
    text = repository.read(DECLARATION_PATH, at, deadline)
    if isinstance(text, Absent):
        return Declaration.none
    return parse_declaration(text)
