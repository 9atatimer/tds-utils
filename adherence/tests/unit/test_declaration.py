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


def test_parse_declaration_reads_the_records_it_names() -> None:
    """Given a [records] table naming the design and the architecture record,
    When it is parsed, Then the declaration carries both paths."""
    declaration = parse_declaration(
        b'[records]\ndesign = "docs/D.md"\narchitecture = "docs/A.md"\n'
    )

    assert isinstance(declaration, Declaration)
    assert declaration.records is not None
    assert (declaration.records.design, declaration.records.architecture) == (
        "docs/D.md",
        "docs/A.md",
    )


@pytest.mark.parametrize(
    "table",
    [
        b'[records]\ndesign = "docs/D.md"\n',
        b'[records]\ndesign = "d"\narchitecture = 3\n',
        b'[records]\ndesign = "d"\narchitecture = "a"\nradar = "r"\n',
        b'records = "docs/D.md"\n',
    ],
)
def test_parse_declaration_with_a_malformed_records_table_is_unreadable(
    table: bytes,
) -> None:
    """Given a [records] table missing a record, naming one by a non-string,
    with an unknown key, or not a table, When it is parsed, Then it is
    DeclarationUnreadable naming records."""
    answer = parse_declaration(table)

    assert isinstance(answer, DeclarationUnreadable)
    assert "records" in answer.reason


def test_parse_declaration_reads_the_radar_it_names() -> None:
    """Given a [radar] table naming the radar by a path, When it is parsed,
    Then the declaration carries that path."""
    declaration = parse_declaration(b'[radar]\npath = "docs/TECH_RADAR.md"\n')

    assert isinstance(declaration, Declaration)
    assert declaration.radar == "docs/TECH_RADAR.md"


def test_parse_declaration_without_a_radar_names_none() -> None:
    """Given no [radar] table, When the declaration is parsed, Then it names
    no radar."""
    declaration = parse_declaration(b'[layers]\ndomain = ["src/**"]\n')

    assert isinstance(declaration, Declaration)
    assert declaration.radar is None


@pytest.mark.parametrize(
    "table",
    [
        b"[radar]\n",
        b'[radar]\npath = ""\n',
        b"[radar]\npath = 3\n",
        b'[radar]\npath = "r"\nring = "Adopt"\n',
        b'radar = "docs/TECH_RADAR.md"\n',
    ],
)
def test_parse_declaration_with_a_malformed_radar_table_is_unreadable(
    table: bytes,
) -> None:
    """Given a [radar] table with no path, an empty or non-string one, an
    unknown key, or not a table, When it is parsed, Then it is
    DeclarationUnreadable naming radar."""
    answer = parse_declaration(table)

    assert isinstance(answer, DeclarationUnreadable)
    assert "radar" in answer.reason


def test_parse_declaration_reads_each_runtime_and_its_paths() -> None:
    """Given a [runtimes] table naming each runtime's path patterns, When it
    is parsed, Then the declaration carries each runtime with its patterns."""
    declaration = parse_declaration(
        b'[runtimes]\ncli = ["src/tool/**"]\nworker = ["src/worker/**", "bin/w"]\n'
    )

    assert isinstance(declaration, Declaration)
    assert [(r.name, r.patterns) for r in declaration.runtimes] == [
        ("cli", ("src/tool/**",)),
        ("worker", ("src/worker/**", "bin/w")),
    ]


@pytest.mark.parametrize(
    "table",
    [
        b'[runtimes]\ncli = "src/**"\n',
        b"[runtimes]\ncli = [3]\n",
        b'runtimes = "cli"\n',
    ],
)
def test_parse_declaration_with_a_malformed_runtimes_table_is_unreadable(
    table: bytes,
) -> None:
    """Given a [runtimes] table whose runtime is not a list of path patterns,
    or that is not a table, When it is parsed, Then it is DeclarationUnreadable
    naming runtimes."""
    answer = parse_declaration(table)

    assert isinstance(answer, DeclarationUnreadable)
    assert "runtimes" in answer.reason
