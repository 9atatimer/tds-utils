"""load_declaration (ARCHITECTURE.ARCH-ADHERENCE.md, Use-case surface).

Driven by its signature with a fake RepositoryPort behind it: the
load_declaration halves of "An undeclared repository is measured" and
"An unreadable declaration is not run". The measure halves are task-058.
"""

from __future__ import annotations

import pytest

from adherence.adapters.fakes import FakeRepository
from adherence.application.load import load_declaration
from adherence.domain.deadline import TimedOut
from adherence.domain.declaration import (
    DECLARATION_PATH,
    Declaration,
    DeclarationUnreadable,
)
from adherence.domain.target import Head
from adherence.ports.repository import Refused

HEAD = Head.working_tree()


def test_load_declaration_with_no_declaration_returns_none() -> None:
    """Given a repository with no adherence.toml, When its declaration is loaded,
    Then it is Declaration.none, so the run measures it as undeclared."""
    repository = FakeRepository({HEAD: {"src/tool.py": b"print('hi')\n"}})

    loaded = load_declaration(HEAD, repository=repository, deadline=None)

    assert loaded is Declaration.none
    assert not loaded.declared


@pytest.mark.parametrize(
    ("text", "named"),
    [
        (b"[layers\n", "line 1"),
        (b"\xff\xfe not utf-8", "utf-8"),
        (b"[surprise]\nx = 1\n", "surprise"),
        (b'[[exemptions]]\ncheck = "Stub"\nunit = "bin/x"\n', "reason"),
        (b'[[exemptions]]\nunit = "bin/x"\nreason = "legacy"\n', "check"),
        (b'exemptions = "Stub"\n', "exemptions"),
    ],
)
def test_load_declaration_that_cannot_be_parsed_is_unreadable(
    text: bytes, named: str
) -> None:
    """Given an adherence.toml that cannot be parsed, When its declaration is
    loaded, Then it is DeclarationUnreadable and its reason names the error."""
    repository = FakeRepository({HEAD: {DECLARATION_PATH: text}})

    loaded = load_declaration(HEAD, repository=repository, deadline=None)

    assert isinstance(loaded, DeclarationUnreadable)
    assert named in loaded.reason


@pytest.mark.parametrize(
    ("answer", "named"),
    [
        (Refused(DECLARATION_PATH, "a symbolic link"), "symbolic link"),
        (TimedOut("read adherence.toml"), "read adherence.toml"),
    ],
)
def test_load_declaration_that_cannot_be_read_is_unreadable(
    answer: Refused | TimedOut, named: str
) -> None:
    """Given an adherence.toml the repository will not or cannot hand over,
    When its declaration is loaded, Then it is DeclarationUnreadable naming why."""
    repository = FakeRepository({HEAD: {DECLARATION_PATH: answer}})

    loaded = load_declaration(HEAD, repository=repository, deadline=None)

    assert isinstance(loaded, DeclarationUnreadable)
    assert named in loaded.reason


def test_load_declaration_that_parses_is_declared() -> None:
    """Given a well-formed adherence.toml, When its declaration is loaded,
    Then it is a Declaration that is declared, never Declaration.none."""
    text = (
        b'[layers]\ndomain = ["src/tool/domain/**"]\n\n'
        b'[[exemptions]]\ncheck = "Stub"\nunit = "bin/legacy"\n'
        b'reason = "kept until the rewrite"\n'
    )
    repository = FakeRepository({HEAD: {DECLARATION_PATH: text}})

    loaded = load_declaration(HEAD, repository=repository, deadline=None)

    assert isinstance(loaded, Declaration)
    assert loaded.declared


def test_load_declaration_reads_every_declaration_as_one() -> None:
    """Given a root declaration naming the radar and a sub-project one
    naming its layers, When the declaration is loaded, Then it is the two
    read as one, governing both directories."""
    repository = FakeRepository(
        {
            HEAD: {
                DECLARATION_PATH: b'[radar]\npath = "RADAR.md"\n',
                "pkg/adherence.toml": b'[layers]\ndomain = ["core/**"]\n',
                "pkg/core/rules.py": b"x = 1\n",
            }
        }
    )

    loaded = load_declaration(HEAD, repository=repository, deadline=None)

    assert isinstance(loaded, Declaration)
    assert loaded.governed == ("", "pkg")
    assert loaded.radar_for("pkg/core/rules.py") == "RADAR.md"
    assert loaded.layers.globs[0][1] == "pkg/core/**"


def test_load_declaration_with_only_sub_project_declarations_is_declared() -> None:
    """Given declarations only in sub-projects, When the declaration is
    loaded, Then the repository is declared and only those subtrees are
    governed."""
    repository = FakeRepository(
        {HEAD: {"a/adherence.toml": b"[layers]\n", "b/adherence.toml": b"[layers]\n"}}
    )

    loaded = load_declaration(HEAD, repository=repository, deadline=None)

    assert isinstance(loaded, Declaration) and loaded.declared
    assert not loaded.governs("c/x.py") and loaded.governs("b/x.py")


def test_load_declaration_with_a_layer_conflict_on_a_real_path_is_unreadable() -> None:
    """Given two governing declarations placing a file of the tree in two
    layers, When the declaration is loaded, Then it cannot be read, naming
    both files and the path."""
    repository = FakeRepository(
        {
            HEAD: {
                DECLARATION_PATH: b'[layers]\ndomain = ["**/*.py"]\n',
                "pkg/adherence.toml": b'[layers]\nadapters = ["*.py"]\n',
                "pkg/io.py": b"x = 1\n",
            }
        }
    )

    loaded = load_declaration(HEAD, repository=repository, deadline=None)

    assert isinstance(loaded, DeclarationUnreadable)
    assert "pkg/adherence.toml" in loaded.reason and "pkg/io.py" in loaded.reason


def test_load_declaration_names_the_sub_project_file_that_cannot_be_parsed() -> None:
    """Given a sub-project declaration that does not parse, When the
    declaration is loaded, Then it cannot be read, naming that file."""
    repository = FakeRepository(
        {HEAD: {DECLARATION_PATH: b"[layers]\n", "pkg/adherence.toml": b"[layers\n"}}
    )

    loaded = load_declaration(HEAD, repository=repository, deadline=None)

    assert isinstance(loaded, DeclarationUnreadable)
    assert "pkg/adherence.toml" in loaded.reason
