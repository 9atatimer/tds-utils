"""cli/presenters/terminal.py -- a Report as lines for a terminal.

What the laptop, the agent and a CI job's log read (ARCHITECTURE.ARCH-
ADHERENCE.md, Findings and explanations). Evidence, symbols, paths and
reasons are author-controlled text: every ANSI escape sequence, control
character and format character is stripped, so the text can neither
recolour the terminal, rewrite or reorder a line, nor start one; a lone
surrogate (an undecodable byte of a path, as git hands it over) is shown as
U+FFFD, so no output stream refuses it; and every line opens with a label
of the presenter's own, so none reads as a workflow command in a job's log
(Security mitigations).
"""

from __future__ import annotations

import re
import unicodedata

from adherence.domain.coverage import Coverage
from adherence.domain.finding import Finding
from adherence.domain.qualities import CheckKind, Quality
from adherence.domain.questions import Abstention
from adherence.domain.report import Recorded, Report

# --- Constants ---------------------------------------------------------------

# Unicode control (newline and tab included) and format (bidi overrides,
# zero-width) characters: none of them may reach the terminal.
STRIPPED_CATEGORIES = frozenset({"Cc", "Cf"})
# A lone surrogate, as surrogateescape decodes a byte that is not UTF-8:
# no encoder writes it, so it is shown as the replacement character.
SURROGATE = "Cs"
REPLACEMENT = "\ufffd"
# An escape sequence whole, parameters included, so stripping its ESC never
# leaves them behind as text: CSI (7- and 8-bit), OSC and the string
# controls up to their terminator, and the two-byte escapes.
ANSI_ESCAPE = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"
    r"|\x9b[0-?]*[ -/]*[@-~]"
    r"|\x1b[\]PX^_][^\x07\x1b]*(?:\x07|\x1b\\)?"
    r"|\x1b[ -/]*[0-~]"
)

# --- Pure helpers ------------------------------------------------------------


def safe_text(text: str) -> str:
    """Author-controlled text with every escape sequence, control and format
    character removed, so it can neither start a line nor reorder one, and
    every lone surrogate replaced, so every stream can write it."""
    return "".join(
        REPLACEMENT if unicodedata.category(ch) == SURROGATE else ch
        for ch in ANSI_ESCAPE.sub("", text)
        if unicodedata.category(ch) not in STRIPPED_CATEGORIES
    )


def _kind(finding: Finding) -> str:
    if finding.kind is CheckKind.JUDGED and finding.confidence is not None:
        return f"judged, confidence {finding.confidence:.2f}"
    return finding.kind.value


def _finding_lines(label: str, finding: Finding) -> list[str]:
    unit = finding.unit
    where = f"{finding.evidence.path}:{finding.evidence.line}"
    symbol = f" {unit.symbol}" if unit.symbol else ""
    layer = finding.layer.value if finding.layer is not None else "no layer"
    reached = f" -> {finding.reached.value}" if finding.reached is not None else ""
    lines = [
        f"  {label}  {finding.check.quality.value} / {finding.check.name}"
        f" ({_kind(finding)})",
        safe_text(f"    at: {where}{symbol} ({unit.kind.value}, {layer}{reached})"),
        safe_text(f"    names: {finding.subject}"),
        safe_text(f"    line: {finding.evidence.text}"),
    ]
    if finding.exempt is not None:
        lines.append(safe_text(f"    exempt: {finding.exempt}"))
    return lines


def _abstention_line(abstention: Abstention) -> str:
    check = abstention.check
    return safe_text(
        f"  abstained  {check.quality.value} / {check.name}"
        f" (confidence {abstention.confidence:.2f}): {abstention.subject}"
    )


def _coverage_line(coverage: Coverage) -> str:
    what = " on ".join(p for p in (coverage.check, coverage.path) if p) or "the run"
    return safe_text(f"  coverage  {what}: {coverage.reason}")


def _quality_lines(report: Report, quality: Quality) -> list[str]:
    ran = ", ".join(c.name for c in report.ran_in(quality)) or "none"
    lines = [f"{quality.value}: ran {ran}"]
    for finding in report.findings_of(quality):
        label = finding.provenance.value if finding.provenance else "finding"
        lines.extend(_finding_lines(label, finding))
    return lines


def _headline(report: Report) -> list[str]:
    if report.not_run_reason is not None:
        return [safe_text(f"not run: {report.not_run_reason}")]
    if report.verdict is None:
        return ["measured"]
    return [
        f"verdict: {report.verdict.value}",
        *(safe_text(f"  why: {reason}") for reason in report.reasons),
    ]


# --- Presenters --------------------------------------------------------------


def report_text(report: Report, recorded: Recorded | None = None) -> str:
    """The report as terminal lines: the verdict and why; per quality, the
    checks that ran and each finding with what fixes it; the findings
    removed, the abstentions, the notices, the coverage, and whether the
    report was kept."""
    lines = _headline(report)
    if report.not_run_reason is None:
        for quality in Quality:
            lines.extend(_quality_lines(report, quality))
    for finding in report.removed:
        lines.extend(_finding_lines("removed", finding))
    lines.extend(_abstention_line(a) for a in report.abstentions)
    lines.extend(safe_text(f"  notice  {n.message}") for n in report.notices)
    lines.extend(_coverage_line(c) for c in report.coverage)
    if recorded is not None and recorded.notice is not None:
        lines.append(safe_text(f"  notice  {recorded.notice.message}"))
    return "\n".join(lines)
