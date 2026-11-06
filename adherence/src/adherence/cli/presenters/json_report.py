"""cli/presenters/json_report.py -- a Report as a JSON document.

The machine form `adhere measure --json` and `adhere judge --json` print
(ARCHITECTURE.ARCH-ADHERENCE.md, Findings and explanations): for a change,
also the verdict and why, each finding's provenance and exemption, the
findings removed, and whether the report was kept. Author-controlled text
travels as JSON strings, which escape every control character.
"""

from __future__ import annotations

import json

from adherence.domain.coverage import Coverage
from adherence.domain.finding import Finding
from adherence.domain.qualities import Quality
from adherence.domain.report import Recorded, Report

# --- Presenters --------------------------------------------------------------


def _finding(finding: Finding) -> dict[str, object]:
    unit = finding.unit
    return {
        "identity": finding.identity,
        "quality": finding.check.quality.value,
        "check": finding.check.name,
        "kind": finding.kind.value,
        "path": unit.path,
        "symbol": unit.symbol,
        "unit_kind": unit.kind.value,
        "layer": finding.layer.value if finding.layer is not None else None,
        "reached": finding.reached.value if finding.reached is not None else None,
        "subject": finding.subject,
        "provenance": (
            finding.provenance.value if finding.provenance is not None else None
        ),
        "exempt": finding.exempt,
        "evidence": {
            "path": finding.evidence.path,
            "line": finding.evidence.line,
            "text": finding.evidence.text,
        },
    }


def _coverage(coverage: Coverage) -> dict[str, object]:
    return {"check": coverage.check, "path": coverage.path, "reason": coverage.reason}


def report_document(
    report: Report, recorded: Recorded | None = None
) -> dict[str, object]:
    """The report as plain data: for a change, the verdict and why; per
    quality, the checks that ran and their findings; the findings removed;
    the notices and the coverage; and whether the report was kept."""
    document: dict[str, object] = {
        "verdict": report.verdict.value if report.verdict is not None else None,
        "reasons": list(report.reasons),
        "not_run": report.not_run_reason,
        "qualities": [
            {
                "quality": quality.value,
                "ran": [check.name for check in report.ran_in(quality)],
                "findings": [_finding(f) for f in report.findings_of(quality)],
            }
            for quality in Quality
        ],
        "removed": [_finding(f) for f in report.removed],
        "notices": [notice.message for notice in report.notices],
        "coverage": [_coverage(c) for c in report.coverage],
    }
    if recorded is not None:
        document["recorded"] = {
            "kept": recorded.kept,
            "notice": recorded.notice.message if recorded.notice else None,
        }
    return document


def report_json(report: Report, recorded: Recorded | None = None) -> str:
    """The report as an indented JSON document."""
    return json.dumps(report_document(report, recorded), indent=2)
