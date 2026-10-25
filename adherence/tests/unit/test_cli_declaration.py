"""`adhere declaration check`: the entry point over the working tree's
adherence.toml, the debugging step for "A declaration that does not
parse" (ARCHITECTURE.ARCH-ADHERENCE.md, Operability)."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from adherence.cli.main import main

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "declaration"


def _check(root: Path) -> tuple[int, str]:
    result = CliRunner().invoke(main, ["declaration", "check", "--root", str(root)])
    return result.exit_code, result.output


def test_declaration_check_of_a_readable_declaration_passes_and_lists_refusals() -> (
    None
):
    """Given a readable declaration that exempts a Declared check, When it is
    checked, Then it exits zero, counts the honored exemption, and reports
    the refused one with the reason."""
    code, output = _check(FIXTURES / "declared")

    assert code == 0, output
    assert "readable" in output and "1 exemption" in output
    assert "refused" in output and "Covered" in output and "Declared" in output


def test_declaration_check_of_an_unreadable_declaration_fails_naming_it() -> None:
    """Given an adherence.toml that does not parse, When it is checked,
    Then it exits non-zero and names the parse error."""
    code, output = _check(FIXTURES / "unreadable")

    assert code == 1
    assert "unreadable" in output and "line 1" in output


def test_declaration_check_with_no_declaration_says_undeclared(tmp_path: Path) -> None:
    """Given a repository with no adherence.toml, When it is checked,
    Then it exits zero and says the repository is measured as undeclared."""
    code, output = _check(tmp_path)

    assert code == 0, output
    assert "undeclared" in output
