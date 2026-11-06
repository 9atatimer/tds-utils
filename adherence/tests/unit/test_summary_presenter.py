"""The PR job summary: a Report as markdown a reviewer reads on the run."""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import replace

from adherence.cli.presenters.summary import report_summary
from adherence.domain.coverage import Coverage
from adherence.domain.finding import Evidence, Finding, Notice, Provenance
from adherence.domain.model import Layer, Unit, UnitKind
from adherence.domain.qualities import catalog_check
from adherence.domain.report import Recorded, Report, Verdict
from tests import report_kit

# A table cell boundary: a pipe no backslash escapes.
CELL = re.compile(r"(?<!\\)\|")

UNIT = Unit("src/app/domain/rules.py", UnitKind.FUNCTION, "tidy", 2, 3, Layer.DOMAIN)
INTRODUCED = Finding(
    catalog_check("Arrow"),
    UNIT,
    Layer.DOMAIN,
    "adapters.http imported from the domain",
    Evidence(UNIT.path, 2, "from app.adapters import http"),
    reached=Layer.ADAPTERS,
    provenance=Provenance.INTRODUCED,
)
EXISTING = replace(
    INTRODUCED,
    check=catalog_check("Complexity"),
    subject="tidy: complexity 17 over the ceiling 15",
    provenance=Provenance.EXISTING,
)
REPORT = Report(
    ran=(catalog_check("Arrow"), catalog_check("Complexity"), catalog_check("Stub")),
    findings=(INTRODUCED, EXISTING),
    notices=(Notice("the base report was measured again"),),
    coverage=(
        Coverage("emacs lisp: no analyzer measures this language", path="a.el"),
        Coverage("emacs lisp: no analyzer measures this language", path="b.el"),
        Coverage("timed out", check="Duplication"),
    ),
    verdict=Verdict.LOWERED,
    reasons=("Arrow on src/app/domain/rules.py was introduced",),
    removed=(replace(EXISTING, subject="tidy: complexity 16 over the ceiling 15"),),
)


def test_the_verdict_and_its_reasons_head_the_summary() -> None:
    """Given a lowered report, When it is summarized, Then the first heading
    names the verdict and each reason follows it."""
    text = report_summary(REPORT)

    first_heading = next(line for line in text.splitlines() if line.startswith("#"))
    assert "lowered" in first_heading
    assert "Arrow on src/app/domain/rules.py was introduced" in text


def test_an_introduced_finding_is_listed_and_an_existing_one_is_counted() -> None:
    """Given one introduced and one existing finding, When summarized, Then
    the introduced one appears with its check, unit, line and subject, and
    the existing one is a count against its quality, not a row."""
    text = report_summary(REPORT)

    assert "adapters.http imported from the domain" in text
    assert "src/app/domain/rules.py:2" in text
    assert "tidy: complexity 17 over the ceiling 15" not in text
    assert "| Complete | 2 | 0 | 1 |" in text
    assert "| Hexagonal | 1 | 1 | 0 |" in text


def test_removed_findings_notices_and_coverage_are_counted() -> None:
    """Given removed findings, a notice and coverage gaps, When summarized,
    Then the removed count, the notice and each coverage reason with its
    count appear."""
    text = report_summary(REPORT)

    assert "removed" in text.lower() and "1" in text
    assert "the base report was measured again" in text
    assert "emacs lisp: no analyzer measures this language" in text
    assert "| 2 |" in text
    assert "timed out" in text


def test_author_text_cannot_break_the_table_or_inject_markup() -> None:
    """Given a finding whose subject and evidence carry a pipe, angle
    brackets, a backtick and a bidi override, When summarized, Then each
    is escaped or removed so the row stays one row of plain text."""
    forged = replace(
        INTRODUCED,
        subject="a | b <img src=x> `tick` ‮",
        evidence=Evidence("x | y.py", 1, "<script>"),
    )
    text = report_summary(replace(REPORT, findings=(forged,)))

    assert "a \\| b" in text and "x \\| y.py" in text
    assert "<img" not in text and "<script>" not in text
    assert "&lt;img" in text
    assert "‮" not in text
    assert "`tick`" not in text


def test_a_report_not_run_says_why_and_nothing_else() -> None:
    """Given a report that was not run, When summarized, Then the summary
    names the reason and lists no quality table."""
    text = report_summary(Report.not_run("adherence.toml: line 3: bad key"))

    assert "not run" in text
    assert "adherence.toml: line 3: bad key" in text
    assert "| Quality |" not in text


def test_whether_the_report_was_kept_is_said() -> None:
    """Given the record of a report that was not kept, When summarized with
    it, Then the summary says so with the notice."""
    text = report_summary(
        REPORT, Recorded(kept=False, notice=Notice("the store is read-only"))
    )

    assert "not kept" in text and "the store is read-only" in text


def test_a_hostile_report_leaves_no_escape_control_or_broken_row() -> None:
    """Given a report whose author text carries ANSI escapes, control and
    bidi characters, HTML and table syntax on every surface, When
    summarized, Then no escape's parameters leak as text, no control or
    format character survives, and every row of each table keeps its
    table's columns."""
    text = report_summary(report_kit.REPORT, report_kit.NOT_KEPT)

    assert "[2K" not in text and "[31m" not in text and "0;owned" not in text
    for line in text.splitlines():
        assert not [ch for ch in line if unicodedata.category(ch) in {"Cc", "Cf"}]
    tables: list[list[str]] = [[]]
    for line in text.splitlines():
        if line.startswith("|"):
            tables[-1].append(line)
        elif tables[-1]:
            tables.append([])
    for table in (t for t in tables if t):
        assert len({len(CELL.findall(line)) for line in table}) == 1, table


def test_author_text_leaves_no_autolink_or_mention() -> None:
    """Given a finding's subject, a reason, a notice and a coverage reason
    carrying scheme URLs, www hosts, emails and @mentions, When summarized,
    Then none of them survives as text GFM turns into a link or a mention
    by itself, read with the backslash escapes and entities undone, so the
    verdict does not hang on the order in which a renderer reads escapes
    and autolinks; a location's line number keeps its colon, even when the
    file is named like a scheme."""
    links = report_kit.LINKS
    forged = replace(INTRODUCED, subject=links, evidence=Evidence("bin/ftp", 12, links))
    text = report_summary(
        replace(
            REPORT,
            findings=(forged,),
            reasons=(links,),
            notices=(Notice(links),),
            coverage=(Coverage(links, check="Duplication"),),
        )
    )

    assert "bin/ftp:12" in text
    shown = html.unescape(re.sub(r"\\(.)", r"\1", text)).replace("bin/ftp:12", "")
    assert shown.count("evil") >= 4 * links.count("evil"), shown
    assert not re.search(r"(?i)(https?|ftp|mailto|xmpp):", shown), shown
    assert not re.search(r"(?i)www\.", shown), shown
    assert not re.search(r"@\w", shown), shown


def test_coverage_of_many_units_for_one_reason_is_one_row() -> None:
    """Given 5000 coverage items of one check and one reason, each on its
    own unit, When summarized, Then they are one row with their count, and
    the summary stays far under the step summary's 1 MiB."""
    coverage = tuple(
        Coverage("implemented was not asked", "Done", f"src/m{n}.py", f"f{n}: x")
        for n in range(5000)
    )
    text = report_summary(replace(REPORT, coverage=coverage))

    assert "| Done: implemented was not asked | 5000 |" in text
    assert len(text.encode("utf-8")) < 64 * 1024
