"""domain/declaration: parse and validation, values in and values out."""

from __future__ import annotations

import pytest
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


def _exempting(check: str) -> bytes:
    return (
        f'[[exemptions]]\ncheck = "{check}"\nunit = "src/tool/new.py"\n'
        f'reason = "the owner says so"\n'
    ).encode()


@pytest.mark.parametrize("check", ["Covered", "Record kept"])
def test_parse_declaration_exempting_a_declared_check_refuses_it(check: str) -> None:
    """Given a declaration that exempts a check of the Declared quality,
    When it is parsed, Then the exemption is refused, with a reason to report,
    and the declaration is otherwise read."""
    declaration = parse_declaration(_exempting(check))

    assert isinstance(declaration, Declaration)
    assert declaration.exemptions == ()
    [refusal] = declaration.refused_exemptions
    assert refusal.exemption.check == check
    assert "Declared" in refusal.reason


def test_parse_declaration_exempting_another_check_honors_it() -> None:
    """Given a declaration that exempts a check outside the Declared quality,
    When it is parsed, Then the exemption stands and nothing is refused."""
    declaration = parse_declaration(_exempting("Stub"))

    assert isinstance(declaration, Declaration)
    assert [e.check for e in declaration.exemptions] == ["Stub"]
    assert declaration.refused_exemptions == ()


def test_parse_declaration_nested_past_the_parser_is_unreadable() -> None:
    """Given an adherence.toml nested deeper than the TOML parser can follow,
    When it is parsed, Then it is DeclarationUnreadable, never a crash."""
    text = b"a = " + b"[" * 5000 + b"]" * 5000 + b"\n"

    assert isinstance(parse_declaration(text), DeclarationUnreadable)


def test_parse_declaration_with_an_integer_past_the_parser_is_unreadable() -> None:
    """Given an adherence.toml holding an integer longer than Python will
    convert, When it is parsed, Then it is DeclarationUnreadable, never a crash."""
    text = b"[limits]\ncomplexity = " + b"1" * 5000 + b"\n"

    assert isinstance(parse_declaration(text), DeclarationUnreadable)
