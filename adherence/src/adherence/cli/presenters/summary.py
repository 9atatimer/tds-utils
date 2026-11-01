"""cli/presenters/summary.py -- a Report as the PR job summary, in markdown.

What the reusable workflow writes to the job summary: the verdict, the
findings, the notices and the coverage (ARCHITECTURE.ARCH-ADHERENCE.md,
Mechanism > Findings and explanations). Evidence, symbols, paths and
reasons are author-controlled: escape sequences and control characters
are stripped, every markdown metacharacter is backslash-escaped, then
every HTML special is an entity, so no tag, link, emphasis or table cell
of the author's renders (Security mitigations).
"""

from __future__ import annotations

import html
import re

from adherence.cli.presenters.terminal import safe_text
from adherence.domain.coverage import Coverage
from adherence.domain.finding import Finding
from adherence.domain.qualities import CheckKind
from adherence.domain.questions import Abstention
from adherence.domain.report import Recorded, Report

# --- Constants ---------------------------------------------------------------

# CommonMark's backslash-escapable punctuation that can open markup; < and >
# become entities, which open nothing.
MARKDOWN = re.compile(r"([\\`*_{}\[\]()#+\-.!|~])")
HEADER = (
    "| Provenance | Finding | Kind | Location | Names | Evidence | Exempt |",
    "|---|---|---|---|---|---|---|",
)

# --- Pure helpers ------------------------------------------------------------


def escaped(text: str) -> str:
    """Author-controlled text made inert in markdown and HTML."""
    return html.escape(MARKDOWN.sub(r"\\\1", safe_text(text)), quote=True)


def _kind(finding: Finding) -> str:
    if finding.kind is CheckKind.JUDGED and finding.confidence is not None:
        return f"judged, confidence {finding.confidence:.2f}"
    return finding.kind.value


def _row(label: str, finding: Finding) -> str:
    evidence = finding.evidence
    symbol = f" {finding.unit.symbol}" if finding.unit.symbol else ""
    cells = (
        label,
        f"{finding.check.quality.value} / {finding.check.name}",
        escaped(_kind(finding)),
        escaped(f"{evidence.path}:{evidence.line}{symbol}"),
        escaped(finding.subject),
        escaped(evidence.text),
        escaped(finding.exempt or ""),
    )
    return "| " + " | ".join(cells) + " |"


def _table(rows: list[str]) -> list[str]:
    return [*HEADER, *rows] if rows else []


def _abstention(abstention: Abstention) -> str:
    check = abstention.check
    return "- " + escaped(
        f"{check.quality.value} / {check.name} on {abstention.unit.path}"
        f" (confidence {abstention.confidence:.2f}): {abstention.subject}"
    )


def _coverage(coverage: Coverage) -> str:
    what = " on ".join(p for p in (coverage.check, coverage.path) if p) or "the run"
    return "- " + escaped(f"{what}: {coverage.reason}")


def _section(title: str, lines: list[str]) -> list[str]:
    return ["", f"### {title}", "", *lines] if lines else []


def _headline(report: Report) -> list[str]:
    if report.not_run_reason is not None:
        return ["## adherence: not run", "", escaped(report.not_run_reason)]
    verdict = report.verdict.value if report.verdict is not None else "measured"
    return [
        f"## adherence: {verdict}",
        *([""] if report.reasons else []),
        *("- " + escaped(reason) for reason in report.reasons),
    ]


# --- Presenters --------------------------------------------------------------


def report_summary(report: Report, recorded: Recorded | None = None) -> str:
    """The report as job-summary markdown: the verdict and why, the findings
    as a table, then the removed findings, the abstentions, the notices and
    the coverage, and a report not kept."""
    notices = [n.message for n in report.notices]
    if recorded is not None and recorded.notice is not None:
        notices.append(recorded.notice.message)
    lines = [
        *_headline(report),
        *_section(
            "Findings",
            _table(
                [
                    _row(f.provenance.value if f.provenance else "finding", f)
                    for f in report.findings
                ]
            ),
        ),
        *_section("Removed", _table([_row("removed", f) for f in report.removed])),
        *_section("Abstained", [_abstention(a) for a in report.abstentions]),
        *_section("Notices", ["- " + escaped(n) for n in notices]),
        *_section("Coverage missing", [_coverage(c) for c in report.coverage]),
    ]
    return "\n".join(lines)
