"""Given the chores CLI, When invoked with --version, Then it reports its version."""

from __future__ import annotations

from click.testing import CliRunner

from chores import __version__
from chores.cli.main import main


def test_version_flag_reports_package_version() -> None:
    """Given the CLI, When --version is passed, Then output carries __version__."""
    result = CliRunner().invoke(main, ["--version"])

    assert result.exit_code == 0
    assert __version__ in result.output
