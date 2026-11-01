"""cli/presenters/terminal.py -- a Report as lines for a terminal.

What the laptop, the agent and a CI job's log read (ARCHITECTURE.ARCH-
ADHERENCE.md, Findings and explanations). Evidence, symbols, paths and
reasons are author-controlled text: every ANSI escape sequence, control
character and format character is stripped (plain.without_controls), so
the text can neither recolour the terminal, rewrite or reorder a line, nor
start one; and every
line opens with a label of the presenter's own, so none reads as a
workflow command in a job's log (Security mitigations).
"""

from __future__ import annotations

from adherence.cli.presenters.plain import without_controls
from adherence.domain.coverage import Coverage
from adherence.domain.finding import Finding
from adherence.domain.qualities import CheckKind, Quality
from adherence.domain.questions import Abstention
from adherence.domain.report import Recorded, Report

# --- Pure helpers ------------------------------------------------------------


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
        without_controls(
            f"    at: {where}{symbol} ({unit.kind.value}, {layer}{reached})"
        ),
        without_controls(f"    names: {finding.subject}"),
        without_controls(f"    line: {finding.evidence.text}"),
    ]
    if finding.exempt is not None:
        lines.append(without_controls(f"    exempt: {finding.exempt}"))
    return lines


def _abstention_line(abstention: Abstention) -> str:
    check = abstention.check
    return without_controls(
        f"  abstained  {check.quality.value} / {check.name}"
        f" (confidence {abstention.confidence:.2f}): {abstention.subject}"
    )


def _coverage_line(coverage: Coverage) -> str:
    what = " on ".join(p for p in (coverage.check, coverage.path) if p) or "the run"
    return without_controls(f"  coverage  {what}: {coverage.reason}")


def _quality_lines(report: Report, quality: Quality) -> list[str]:
    ran = ", ".join(c.name for c in report.ran_in(quality)) or "none"
    lines = [f"{quality.value}: ran {ran}"]
    for finding in report.findings_of(quality):
        label = finding.provenance.value if finding.provenance else "finding"
        lines.extend(_finding_lines(label, finding))
    return lines


def _headline(report: Report) -> list[str]:
    if report.not_run_reason is not None:
        return [without_controls(f"not run: {report.not_run_reason}")]
    if report.verdict is None:
        return ["measured"]
    return [
        f"verdict: {report.verdict.value}",
        *(without_controls(f"  why: {reason}") for reason in report.reasons),
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
    lines.extend(without_controls(f"  notice  {n.message}") for n in report.notices)
    lines.extend(_coverage_line(c) for c in report.coverage)
    if recorded is not None and recorded.notice is not None:
        lines.append(without_controls(f"  notice  {recorded.notice.message}"))
    return "\n".join(lines)
