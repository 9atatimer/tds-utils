"""Unit tests for the Click CLI (plan/apply, exit codes)."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from orgmarks.app.cli import cli

_TAXONOMY = """
version: 1
intents:
  - name: work
  - name: fun
reference:
  root: other/Reference
rules:
  - match: {domain: example.com}
    folder: work/dev
    ref: technical/dev
    source: human
"""

_HTML = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p>
    <DT><H3 PERSONAL_TOOLBAR_FOLDER="true">Bookmarks bar</H3>
    <DL><p>
        <DT><A HREF="https://example.com/a" ADD_DATE="1">Alpha</A>
    </DL><p>
</DL><p>
"""


def _write(tmp_path: Path) -> tuple[Path, Path]:
    tax = tmp_path / "taxonomy.yml"
    tax.write_text(_TAXONOMY)
    html = tmp_path / "bookmarks.html"
    html.write_text(_HTML)
    return tax, html


def test_plan_is_read_only_and_prints_report(tmp_path: Path) -> None:
    """Given valid inputs, When plan runs, Then it prints and writes nothing."""
    tax, html = _write(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["plan", "--input", str(html), "--taxonomy", str(tax)])
    assert result.exit_code == 0
    assert "orgmarks plan" in result.output
    assert not list(tmp_path.glob("bookmarks-organized-*.html"))


def test_apply_writes_html_and_exits_zero(tmp_path: Path) -> None:
    """Given valid inputs, When apply runs, Then a dated HTML file is written."""
    tax, html = _write(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "apply",
            "--input",
            str(html),
            "--taxonomy",
            str(tax),
            "--output-dir",
            str(tmp_path),
            "--date",
            "2026-07-23",
        ],
    )
    assert result.exit_code == 0
    out = tmp_path / "bookmarks-organized-2026-07-23.html"
    assert out.exists()
    assert "https://example.com/a" in out.read_text()


def test_invalid_taxonomy_exits_two(tmp_path: Path) -> None:
    """Given an invalid taxonomy, When plan runs, Then exit code is 2."""
    tax = tmp_path / "taxonomy.yml"
    tax.write_text(
        "version: 1\nintents: []\nbogus: 5\nreference:\n  root: other/Reference\n"
    )
    html = tmp_path / "bookmarks.html"
    html.write_text(_HTML)
    runner = CliRunner()
    result = runner.invoke(cli, ["plan", "--input", str(html), "--taxonomy", str(tax)])
    assert result.exit_code == 2


def test_unparseable_profile_input_exits_two(tmp_path: Path) -> None:
    """Given broken JSON, When --from-profile runs, Then exit code is 2."""
    tax, _ = _write(tmp_path)
    bad = tmp_path / "Bookmarks"
    bad.write_text("{not valid json")
    runner = CliRunner()
    result = runner.invoke(
        cli, ["plan", "--from-profile", str(bad), "--taxonomy", str(tax)]
    )
    assert result.exit_code == 2


def test_apply_rejects_non_iso_date(tmp_path: Path) -> None:
    """Given a --date with path separators, When apply runs, Then it errors."""
    tax, html = _write(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "apply",
            "--input",
            str(html),
            "--taxonomy",
            str(tax),
            "--output-dir",
            str(tmp_path),
            "--date",
            "../../evil",
        ],
    )
    assert result.exit_code == 2
    assert not list(tmp_path.glob("bookmarks-organized-*.html"))


def test_requires_exactly_one_source(tmp_path: Path) -> None:
    """Given neither input flag, When plan runs, Then it is a usage error."""
    tax, _ = _write(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["plan", "--taxonomy", str(tax)])
    assert result.exit_code != 0
