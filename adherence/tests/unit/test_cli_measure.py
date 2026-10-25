"""`adhere measure` as an entry point, before it reaches the use case."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from adherence.cli.main import main


def test_measure_without_its_adapters_names_the_ports_unbound(tmp_path: Path) -> None:
    """Given the composition root with no adapter yet for records (complexity
    and duplication are bound), When `adhere measure --json` runs, Then it
    exits non-zero naming the unbound port and measures nothing."""
    result = CliRunner().invoke(main, ["measure", "--root", str(tmp_path), "--json"])

    assert result.exit_code == 2
    assert "records" in result.output
    assert "complexity" not in result.output and "duplication" not in result.output


def test_measure_without_json_says_json_is_the_one_format(tmp_path: Path) -> None:
    """Given no output format, When `adhere measure` runs, Then it exits
    non-zero and says --json is the format available."""
    result = CliRunner().invoke(main, ["measure", "--root", str(tmp_path)])

    assert result.exit_code == 2
    assert "--json" in result.output
