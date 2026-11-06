"""`adhere measure` as an entry point, before it reaches the use case."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from adherence.cli.main import main


def test_measure_without_a_format_names_the_formats(tmp_path: Path) -> None:
    """Given no output format, When `adhere measure` runs, Then it exits
    non-zero and names the formats available."""
    result = CliRunner().invoke(main, ["measure", "--root", str(tmp_path)])

    assert result.exit_code == 2
    assert "--format" in result.output and "summary" in result.output
