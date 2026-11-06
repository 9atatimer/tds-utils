"""The output format `adhere measure` and `adhere judge` take."""

from __future__ import annotations

import functools
import json
from pathlib import Path

from click.testing import CliRunner

from adherence.adapters.fakes import FakeComplexity, FakeDuplication
from adherence.cli.main import main
from adherence.container import build


def test_an_unknown_format_is_refused_naming_the_formats(tmp_path: Path) -> None:
    """Given a format the CLI does not have, When `adhere judge` runs, Then
    it exits with a usage error that names json and summary."""
    result = CliRunner().invoke(
        main,
        [
            "judge",
            "--root",
            str(tmp_path),
            "--base",
            "a",
            "--head",
            "b",
            "--format",
            "xml",
        ],
    )

    assert result.exit_code == 2
    assert "json" in result.output and "summary" in result.output


def _run(args: list[str], root: Path) -> tuple[int, str]:
    """The CLI over a root that is no git repository, so every use case ends
    at `not run` before any analyzer is needed and the presenter still runs."""
    builder = functools.partial(
        build, complexity=FakeComplexity(), duplication=FakeDuplication()
    )
    result = CliRunner().invoke(main, [*args, "--root", str(root)], obj=builder)
    return result.exit_code, result.output


def test_json_is_the_short_form_of_format_json(tmp_path: Path) -> None:
    """Given `--json` alone, When `adhere measure` runs, Then the report is
    printed through the json presenter."""
    code, output = _run(["measure", "--json"], tmp_path)

    assert code == 1
    assert "not a git repository" in json.loads(output)["not_run"]


def test_format_summary_prints_the_summary(tmp_path: Path) -> None:
    """Given `--format summary`, When `adhere measure` runs, Then the report
    is printed through the summary presenter."""
    code, output = _run(["measure", "--format", "summary"], tmp_path)

    assert code == 1
    assert output.startswith("## Adherence: not run")
    assert "not a git repository" in output


def test_the_short_form_beside_another_format_is_a_conflict(tmp_path: Path) -> None:
    """Given both `--json` and `--format summary`, When `adhere measure`
    runs, Then it exits with a usage error naming the conflict, and prints
    no report."""
    code, output = _run(["measure", "--json", "--format", "summary"], tmp_path)

    assert code == 2
    assert "conflicts" in output and "## Adherence" not in output


def test_the_short_form_beside_format_json_is_no_conflict(tmp_path: Path) -> None:
    """Given both `--json` and `--format json`, When `adhere measure` runs,
    Then they agree and the report is printed as JSON."""
    code, output = _run(["measure", "--json", "--format", "json"], tmp_path)

    assert code == 1
    assert "not a git repository" in json.loads(output)["not_run"]
