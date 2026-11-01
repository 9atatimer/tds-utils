"""The PR job summary presenter, a pure function over a Report value
(ARCHITECTURE.ARCH-ADHERENCE.md, Mechanism > Findings and explanations:
the findings, notices and verdict in the job summary; Security
mitigations: markdown and HTML escaped in the job summary)."""

from __future__ import annotations

import re
import unicodedata

from adherence.cli.presenters.summary import report_summary
from adherence.domain.report import Report
from tests.report_kit import NOT_KEPT, REPORT

# A table cell boundary: a pipe no backslash escapes.
CELL = re.compile(r"(?<!\\)\|")


def test_report_summary_heads_with_the_verdict_and_tables_the_findings() -> None:
    """Given a judged report, When it is written to the job summary, Then the
    verdict heads it with its reasons, each finding is a table row naming
    its provenance, quality, check, kind and location, and the removed
    findings, abstentions, notices, coverage and a report not kept follow."""
    text = report_summary(REPORT, NOT_KEPT)

    lines = text.splitlines()
    assert lines[0] == "## adherence: lowered"
    assert "Stub on src/app/domain/rules\\.py introduced" in text
    rows = [line for line in lines if line.startswith("| introduced")]
    assert len(rows) == 1 and "Complete / Stub" in rows[0]
    assert "judged, confidence 0\\.93" in text
    assert "### Removed" in text and "### Abstained" in text
    assert "an exemption the change adds is inert" in text
    assert "did not finish before the deadline" in text
    assert "the report was not kept: disk full" in text


def test_report_summary_escapes_markdown_and_html_in_author_text() -> None:
    """Given evidence, a path and an exemption reason carrying HTML, markdown
    and table syntax, ANSI escapes and control characters, When the report
    is written to the job summary, Then no tag, emphasis, link or cell
    boundary of the author's survives, and every table row keeps its
    columns."""
    text = report_summary(REPORT, NOT_KEPT)

    assert "<b>" not in text and "<i>" not in text
    assert "&lt;b&gt;" in text and "&lt;i&gt;here&lt;/i&gt;" in text
    assert "\\|\\*\\_\\[a\\]\\(b\\)" in text
    assert "[31m" not in text and "0;owned" not in text
    for line in text.splitlines():
        assert not [ch for ch in line if unicodedata.category(ch) in {"Cc", "Cf"}]
    table = [line for line in text.splitlines() if line.startswith("|")]
    assert table and len({len(CELL.findall(line)) for line in table}) == 1, table


def test_report_summary_of_a_run_that_did_not_run_says_why() -> None:
    """Given a report the suite could not perform, When it is written to the
    job summary, Then it heads with not run and the escaped reason."""
    text = report_summary(Report.not_run("adherence.toml: <bad> *line*"))

    assert text.splitlines()[0] == "## adherence: not run"
    assert "adherence\\.toml: &lt;bad&gt; \\*line\\*" in text
