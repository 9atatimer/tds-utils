"""domain/declaration: parse and validation, values in and values out."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from adherence.domain.declaration import (
    Declaration,
    DeclarationUnreadable,
    parse_declaration,
)


@given(st.binary())
def test_parse_declaration_of_any_bytes_answers_without_raising(text: bytes) -> None:
    """Given any bytes at all, When they are parsed as a declaration,
    Then the answer is a Declaration or DeclarationUnreadable, never an error."""
    assert isinstance(parse_declaration(text), Declaration | DeclarationUnreadable)
