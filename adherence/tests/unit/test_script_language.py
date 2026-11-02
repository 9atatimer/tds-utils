"""A file with no extension is a source only by its shebang (Issue#638;
ARCHITECTURE.ARCH-ADHERENCE.md, Key Decisions, a shell script by its
shebang): a shell interpreter makes it shell, another interpreter is named
so the file can be reported, and no shebang makes it no source."""

from __future__ import annotations

import pytest

from adherence.domain.model import has_no_extension, script_language


@pytest.mark.parametrize(
    "first",
    [
        b"#!/bin/bash\n",
        b"#!/usr/bin/env bash\n",
        b"#! /bin/sh -e\n",
        b"#!/bin/zsh -f\n",
        b"#!/usr/bin/env -S bash -euo pipefail\n",
        b"#!/bin/dash\n",
        b"#!/bin/ksh\n",
        b"#!/usr/bin/env LC_ALL=C zsh\n",
        b"#!/usr/bin/env -u PAGER bash\n",
        b"#!/usr/bin/env -C /tmp bash\n",
        b"#!/usr/bin/env --unset=PAGER -i bash\n",
    ],
)
def test_a_shell_shebang_makes_a_script_shell(first: bytes) -> None:
    """Given a first line naming a shell, directly or through env, When the
    script's language is read, Then it is shell."""
    assert script_language(first + b"echo hi\n") == "shell"


@pytest.mark.parametrize(
    ("first", "interpreter"),
    [
        (b"#!/usr/bin/env python3\n", "python3"),
        (b"#!/usr/bin/env node\n", "node"),
        (b"#!/usr/bin/perl -w\n", "perl"),
    ],
)
def test_another_interpreter_is_named(first: bytes, interpreter: str) -> None:
    """Given a first line naming an interpreter that is not a shell, When the
    script's language is read, Then it is that interpreter's name."""
    assert script_language(first + b"print(1)\n") == interpreter


@pytest.mark.parametrize(
    "text",
    [b"", b"echo hi\n", b"# a comment\n", b"#!\n", b"#!/usr/bin/env\n", b"\xff\xfe"],
)
def test_no_shebang_is_no_source(text: bytes) -> None:
    """Given a file with no usable shebang, When its language is read, Then
    it has none."""
    assert script_language(text) is None


@pytest.mark.parametrize(
    ("path", "bare"),
    [
        ("bin/tds-release", True),
        ("Makefile", True),
        (".zshenv", True),
        ("bin/run.sh", False),
        ("macos/dot.zshrc", False),
        ("README.md", False),
    ],
)
def test_a_name_with_no_extension_is_told_apart(path: str, bare: bool) -> None:
    """Given a path, When asked whether its name has no extension, Then a
    leading dot alone does not count as one."""
    assert has_no_extension(path) is bare


@pytest.mark.parametrize(
    "first",
    [b"#!/usr/bin/" + b"x" * 200 + b"\n", b"#!/usr/bin/env py<b>thon\n"],
)
def test_an_interpreter_name_out_of_bounds_is_not_repeated(first: bytes) -> None:
    """Given a shebang whose interpreter name is long or carries markup, When
    the script's language is read, Then it is "unknown": the name goes into a
    coverage reason, so it is author text with a bound."""
    assert script_language(first) == "unknown"
