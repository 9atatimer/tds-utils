"""cli/presenters/sarif.py -- a Report as a SARIF 2.1.0 log.

The finding shape the editor, code scanning and the PR read
(ARCHITECTURE.ARCH-ADHERENCE.md, Mechanism > Findings and explanations):
one rule per check of the catalog, one result per finding with its
identity as the partial fingerprint and its provenance and kind as
properties, an exempt finding suppressed with its reason, and the notices
and coverage as the invocation's notifications. Author-controlled text
travels as data fields only, never as markdown (Security mitigations); a
lone surrogate in it (an undecodable byte of a path, as git hands it over)
is U+FFFD in text, while an artifact's uri percent-encodes the real byte.
"""

from __future__ import annotations

import json
import re
from urllib.parse import quote

from adherence.domain.coverage import Coverage
from adherence.domain.finding import Finding, Provenance
from adherence.domain.qualities import CATALOG, Check, CheckKind
from adherence.domain.report import SUITE_VERSION, Recorded, Report

# --- Constants ---------------------------------------------------------------

SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
VERSION = "2.1.0"
TOOL = "adherence"
# The partial fingerprint a finding's identity travels under; the version
# moves only if the identity's digest changes.
FINGERPRINT = "adherenceIdentity/v1"
# The base every artifact URI is relative to: the repository's root.
SOURCE_ROOT = "%SRCROOT%"
NOT_A_SLUG = re.compile(r"[^a-z0-9]+")
RULE_INDEX = {check: index for index, check in enumerate(CATALOG)}
# A lone surrogate, as surrogateescape decodes a byte that is not UTF-8.
SURROGATE = re.compile("[\ud800-\udfff]")
REPLACEMENT = "\ufffd"

# --- Pure helpers ------------------------------------------------------------


def _uri(path: str) -> str:
    """A repository path as a relative uri, percent-encoding its bytes as
    they are on disk, an undecodable one included."""
    return quote(path, errors="surrogateescape")


def _replaced(value: object) -> object:
    """A document with every lone surrogate in its text replaced, so the
    log is valid Unicode JSON."""
    if isinstance(value, str):
        return SURROGATE.sub(REPLACEMENT, value)
    if isinstance(value, dict):
        return {key: _replaced(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_replaced(item) for item in value]
    return value


def _rule_id(check: Check) -> str:
    """A check's rule id: its name, lower-cased and hyphenated."""
    return NOT_A_SLUG.sub("-", check.name.lower()).strip("-")


def _rule(check: Check) -> dict[str, object]:
    return {
        "id": _rule_id(check),
        "name": check.name,
        "shortDescription": {
            "text": f"{check.quality.value} / {check.name} ({check.kind.value})"
        },
        "properties": {"quality": check.quality.value, "kind": check.kind.value},
    }


def _level(finding: Finding) -> str:
    if finding.exempt is not None:
        return "note"
    if finding.provenance is Provenance.INTRODUCED:
        return "error"
    return "warning"


def _location(finding: Finding) -> dict[str, object]:
    evidence = finding.evidence
    physical: dict[str, object] = {
        "artifactLocation": {"uri": _uri(evidence.path), "uriBaseId": SOURCE_ROOT}
    }
    if evidence.line >= 1:
        physical["region"] = {
            "startLine": evidence.line,
            "snippet": {"text": evidence.text},
        }
    location: dict[str, object] = {"physicalLocation": physical}
    if finding.unit.symbol:
        location["logicalLocations"] = [
            {
                "fullyQualifiedName": finding.unit.symbol,
                "kind": finding.unit.kind.value,
            }
        ]
    return location


def _properties(finding: Finding) -> dict[str, object]:
    properties: dict[str, object] = {
        "quality": finding.check.quality.value,
        "check": finding.check.name,
        "kind": finding.kind.value,
        "provenance": (
            finding.provenance.value if finding.provenance is not None else None
        ),
        "subject": finding.subject,
        "unitKind": finding.unit.kind.value,
        "layer": finding.layer.value if finding.layer is not None else None,
        "reached": finding.reached.value if finding.reached is not None else None,
    }
    if finding.kind is CheckKind.JUDGED:
        properties["confidence"] = finding.confidence
    return properties


def _result(finding: Finding) -> dict[str, object]:
    result: dict[str, object] = {
        "ruleId": _rule_id(finding.check),
        "ruleIndex": RULE_INDEX[finding.check],
        "kind": "fail",
        "level": _level(finding),
        "message": {"text": f"{finding.check.name}: {finding.subject}"},
        "locations": [_location(finding)],
        "partialFingerprints": {FINGERPRINT: finding.identity},
        "properties": _properties(finding),
    }
    if finding.exempt is not None:
        result["suppressions"] = [{"kind": "external", "justification": finding.exempt}]
    return result


def _notification(text: str, level: str, **properties: object) -> dict[str, object]:
    notification: dict[str, object] = {"message": {"text": text}, "level": level}
    if properties:
        notification["properties"] = properties
    return notification


def _coverage_notification(coverage: Coverage) -> dict[str, object]:
    what = " on ".join(p for p in (coverage.check, coverage.path) if p) or "the run"
    return _notification(
        f"coverage missing: {what}: {coverage.why}",
        "warning",
        check=coverage.check,
        path=coverage.path,
    )


def _notifications(
    report: Report, recorded: Recorded | None
) -> list[dict[str, object]]:
    found = [
        *(
            [_notification(f"not run: {report.not_run_reason}", "error")]
            if report.not_run_reason is not None
            else []
        ),
        *(_notification(n.message, "note") for n in report.notices),
        *(_coverage_notification(c) for c in report.coverage),
    ]
    if recorded is not None and recorded.notice is not None:
        found.append(_notification(recorded.notice.message, "note"))
    return found


def _removed(finding: Finding) -> dict[str, object]:
    return {
        "identity": finding.identity,
        "check": finding.check.name,
        "path": finding.unit.path,
        "symbol": finding.unit.symbol,
    }


def _run_properties(report: Report) -> dict[str, object]:
    return {
        "verdict": report.verdict.value if report.verdict is not None else None,
        "reasons": list(report.reasons),
        "notRun": report.not_run_reason,
        "removed": [_removed(f) for f in report.removed],
        "abstentions": [
            {
                "check": a.check.name,
                "path": a.unit.path,
                "symbol": a.unit.symbol,
                "subject": a.subject,
                "confidence": a.confidence,
            }
            for a in report.abstentions
        ],
    }


# --- Presenters --------------------------------------------------------------


def report_document(
    report: Report, recorded: Recorded | None = None
) -> dict[str, object]:
    """The report as a SARIF 2.1.0 log, as plain data: one run, its rules
    the catalog's checks, its results the findings, its invocation's
    notifications the notices, the coverage and a report not kept, and the
    verdict, its reasons, the removed findings and the abstentions as the
    run's properties."""
    return {
        "$schema": SCHEMA,
        "version": VERSION,
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": TOOL,
                        "version": SUITE_VERSION,
                        "rules": [_rule(c) for c in CATALOG],
                    }
                },
                "invocations": [
                    {
                        "executionSuccessful": report.not_run_reason is None,
                        "toolExecutionNotifications": _notifications(report, recorded),
                    }
                ],
                "results": [_result(f) for f in report.findings],
                "properties": _run_properties(report),
            }
        ],
    }


def report_sarif(report: Report, recorded: Recorded | None = None) -> str:
    """The report as an indented SARIF 2.1.0 JSON document."""
    return json.dumps(_replaced(report_document(report, recorded)), indent=2)
