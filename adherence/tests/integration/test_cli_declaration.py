"""`adhere declaration check`: the entry point over the working tree's
adherence.toml, the debugging step for "A declaration that does not
parse" (ARCHITECTURE.ARCH-ADHERENCE.md, Operability). Integration tier:
the declarations are found by listing the working tree, which git does."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from adherence.cli.main import main
from tests.fixture_tree import planted_repository
from tests.git_kit import make_repository

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "declaration"


def _repository(tmp_path: Path, files: dict[str, bytes]) -> Path:
    root = tmp_path / "repo"
    make_repository(root, base={}, staged={}, working=files)
    return root


def _check(root: Path) -> tuple[int, str]:
    result = CliRunner().invoke(main, ["declaration", "check", "--root", str(root)])
    return result.exit_code, result.output


def test_declaration_check_of_a_readable_declaration_passes_and_lists_refusals(
    tmp_path: Path,
) -> None:
    """Given a readable declaration that exempts a Declared check, When it is
    checked, Then it exits zero, counts the honored exemption, and reports
    the refused one with the reason."""
    code, output = _check(planted_repository(FIXTURES / "declared", tmp_path / "repo"))

    assert code == 0, output
    assert "readable" in output and "1 exemption" in output
    assert "refused" in output and "Covered" in output and "Declared" in output


def test_declaration_check_of_an_unreadable_declaration_fails_naming_it(
    tmp_path: Path,
) -> None:
    """Given an adherence.toml that does not parse, When it is checked,
    Then it exits non-zero and names the parse error."""
    code, output = _check(
        planted_repository(FIXTURES / "unreadable", tmp_path / "repo")
    )

    assert code == 1
    assert "unreadable" in output and "line 1" in output


def test_declaration_check_with_no_declaration_says_undeclared(tmp_path: Path) -> None:
    """Given a repository with no adherence.toml, When it is checked,
    Then it exits zero and says the repository is measured as undeclared."""
    code, output = _check(_repository(tmp_path, {"tool.py": b"x = 1\n"}))

    assert code == 0, output
    assert "undeclared" in output


def test_declaration_check_never_lets_declaration_text_forge_a_line(
    tmp_path: Path,
) -> None:
    """Given a declaration whose text carries a newline, a tab and a bidi
    override, When it is checked, Then the output has one line per fact and
    none of those characters reaches the terminal."""
    forged = "x\\nadherence.toml: readable, 0 exemptions\\t\\u202e"
    text = f'[[exemptions]]\ncheck = "Covered"\nunit = "{forged}"\nreason = "r"\n'

    code, output = _check(_repository(tmp_path, {"adherence.toml": text.encode()}))

    assert code == 0, output
    lines = output.splitlines()
    assert len(lines) == 2, output
    assert not lines[1].startswith("adherence.toml")
    assert not any(ch in output for ch in "\t‮")


def test_declaration_check_lists_each_declaration_file(tmp_path: Path) -> None:
    """Given a root declaration with one exemption and a sub-project one
    with none, When they are checked, Then it exits zero with one line per
    file, each naming its path, that it reads, and its exemptions."""
    root = _repository(
        tmp_path,
        {
            "adherence.toml": b'[[exemptions]]\ncheck = "Stub"\nunit = "x.py"\n'
            b'reason = "r"\n',
            "pkg/adherence.toml": b'[layers]\ndomain = ["core/**"]\n',
        },
    )

    code, output = _check(root)

    assert code == 0, output
    lines = output.splitlines()
    assert "adherence.toml: readable, 1 exemption" in lines, output
    assert "pkg/adherence.toml: readable, 0 exemptions" in lines, output


def test_declaration_check_fails_when_one_file_is_unreadable(tmp_path: Path) -> None:
    """Given a readable root declaration and a sub-project one that does not
    parse, When they are checked, Then it exits non-zero, the root's line
    says it reads and the sub-project's names its error."""
    root = _repository(
        tmp_path,
        {"adherence.toml": b"[layers]\n", "pkg/adherence.toml": b"[layers\n"},
    )

    code, output = _check(root)

    assert code == 1, output
    assert "adherence.toml: readable, 0 exemptions" in output.splitlines()
    assert any(
        line.startswith("pkg/adherence.toml: unreadable")
        for line in output.splitlines()
    ), output


def test_declaration_check_fails_when_the_files_conflict(tmp_path: Path) -> None:
    """Given two readable declarations that place one file in two layers,
    When they are checked, Then each file's line says it reads, the merge's
    refusal names both, and it exits non-zero."""
    root = _repository(
        tmp_path,
        {
            "adherence.toml": b'[layers]\ndomain = ["**/*.py"]\n',
            "pkg/adherence.toml": b'[layers]\nadapters = ["*.py"]\n',
            "pkg/io.py": b"x = 1\n",
        },
    )

    code, output = _check(root)

    assert code == 1, output
    assert "governing declarations unreadable" in output
    assert "pkg/io.py" in output


def test_declaration_check_names_a_directory_holding_glob_characters(
    tmp_path: Path,
) -> None:
    """Given a sub-project declaration in a directory named with glob
    characters, When it is checked, Then its line names the directory as it
    is, and it reads."""
    root = _repository(
        tmp_path,
        {
            "adherence.toml": b'[layers]\ndomain = ["xy/src/**"]\n',
            "x[y]/adherence.toml": b'[layers]\ntest = ["src/**"]\n',
            "xy/src/dom.py": b"x = 1\n",
            "x[y]/src/t.py": b"x = 1\n",
        },
    )

    code, output = _check(root)

    assert code == 0, output
    assert "x[y]/adherence.toml: readable, 0 exemptions" in output.splitlines()
