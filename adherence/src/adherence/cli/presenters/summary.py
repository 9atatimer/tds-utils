"""cli/presenters/summary.py -- a Report as the PR job summary.

The markdown the CI job writes to its step summary (ARCHITECTURE.
ARCH-ADHERENCE.md, PR surface): the verdict and why, the introduced
findings a reviewer must read as rows, the rest as counts. Evidence,
symbols, paths and subjects are author-controlled text, so every cell is
escaped for markdown and HTML and stripped of control and format
characters (Security mitigations).
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from collections.abc import Sequence

from adherence.domain.coverage import Coverage
from adherence.domain.finding import Finding, Provenance
from adherence.domain.qualities import Quality
from adherence.domain.report import Recorded, Report

# --- Constants ---------------------------------------------------------------

# Unicode control (newline and tab included) and format (bidi overrides,
# zero-width) characters: none of them may reach the summary.
STRIPPED_CATEGORIES = frozenset({"Cc", "Cf"})
# HTML first, so an escaping backslash is never itself escaped as markup.
HTML_ESCAPES = (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"))
# What starts or ends inline markup, or a table cell, inside a cell.
MARKDOWN_SPECIALS = "\\`*_[]|~"

# --- Predicates and helpers --------------------------------------------------


def _escaped(text: str) -> str:
    """Author-controlled text as one plain-text markdown cell: control and
    format characters removed, HTML escaped, markdown specials escaped."""
    plain = "".join(
        ch for ch in text if unicodedata.category(ch) not in STRIPPED_CATEGORIES
    )
    for raw, escaped in HTML_ESCAPES:
        plain = plain.replace(raw, escaped)
    return "".join(f"\\{ch}" if ch in MARKDOWN_SPECIALS else ch for ch in plain)


def _row(*cells: str) -> str:
    return "| " + " | ".join(cells) + " |"


def _table(header: tuple[str, ...], rows: Sequence[tuple[str, ...]]) -> list[str]:
    return [
        _row(*header),
        _row(*("---" for _ in header)),
        *(_row(*row) for row in rows),
    ]


def _location(finding: Finding) -> str:
    where = f"{finding.evidence.path}:{finding.evidence.line}"
    if finding.unit.symbol:
        where = f"{where} {finding.unit.symbol}"
    return _escaped(where)


def _is(finding: Finding, provenance: Provenance) -> bool:
    return finding.provenance is provenance


# --- Sections ----------------------------------------------------------------


def _head(report: Report, recorded: Recorded | None) -> list[str]:
    verdict = report.verdict.value if report.verdict is not None else "measured"
    lines = [f"## Adherence: {verdict}", ""]
    lines.extend(f"- {_escaped(reason)}" for reason in report.reasons)
    if recorded is not None and not recorded.kept:
        why = recorded.notice.message if recorded.notice is not None else ""
        lines.append(f"- report not kept: {_escaped(why)}")
    return lines


def _qualities(report: Report) -> list[str]:
    rows = []
    for quality in Quality:
        findings = report.findings_of(quality)
        rows.append(
            (
                quality.value,
                str(len(report.ran_in(quality))),
                str(sum(1 for f in findings if _is(f, Provenance.INTRODUCED))),
                str(sum(1 for f in findings if not _is(f, Provenance.INTRODUCED))),
            )
        )
    return ["", *_table(("Quality", "Checks ran", "Introduced", "Existing"), rows)]


def _introduced(report: Report) -> list[str]:
    rows = [
        (
            _escaped(f.check.quality.value),
            _escaped(f.check.name),
            _location(f),
            _escaped(f.subject),
        )
        for f in report.findings
        if _is(f, Provenance.INTRODUCED)
    ]
    if not rows:
        return []
    return [
        "",
        f"### Introduced ({len(rows)})",
        "",
        *_table(("Quality", "Check", "Where", "Finding"), rows),
    ]


def _counts(report: Report) -> list[str]:
    lines = []
    if report.removed:
        lines.append(f"- removed since the base: {len(report.removed)}")
    exempt = sum(1 for f in report.findings if f.exempt is not None)
    if exempt:
        lines.append(f"- exempt: {exempt}")
    return ["", *lines] if lines else []


def _notices(report: Report) -> list[str]:
    if not report.notices:
        return []
    return [
        "",
        "### Notices",
        "",
        *(f"- {_escaped(notice.message)}" for notice in report.notices),
    ]


def _coverage_key(coverage: Coverage) -> str:
    reason = coverage.reason
    return f"{coverage.check}: {reason}" if coverage.check else reason


def _coverage(report: Report) -> list[str]:
    if not report.coverage:
        return []
    counted = Counter(_coverage_key(c) for c in report.coverage)
    rows = [(_escaped(reason), str(n)) for reason, n in counted.most_common()]
    return [
        "",
        f"### Not measured ({len(report.coverage)})",
        "",
        *_table(("Reason", "Count"), rows),
    ]


# --- Presenter ---------------------------------------------------------------


def report_summary(report: Report, recorded: Recorded | None = None) -> str:
    """The report as the markdown of a job summary: the verdict and its
    reasons, the quality table, the introduced findings as rows, the
    removed and exempt counts, the notices, and the coverage by reason."""
    if report.not_run_reason is not None:
        return "\n".join(
            ["## Adherence: not run", "", f"- {_escaped(report.not_run_reason)}", ""]
        )
    lines = [
        *_head(report, recorded),
        *_qualities(report),
        *_introduced(report),
        *_counts(report),
        *_notices(report),
        *_coverage(report),
    ]
    return "\n".join(lines) + "\n"
