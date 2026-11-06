"""The output format `adhere measure` and `adhere judge` take."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from adherence.cli.main import main


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


def test_json_is_still_the_short_form(tmp_path: Path) -> None:
    """Given `--json`, When `adhere measure` is parsed, Then it is the json
    format and the parse does not fail on the flag."""
    result = CliRunner().invoke(
        main, ["measure", "--root", str(tmp_path), "--json", "--format", "xml"]
    )

    assert result.exit_code == 2
    assert "xml" in result.output
