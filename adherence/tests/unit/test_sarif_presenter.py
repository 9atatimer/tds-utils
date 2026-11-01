"""The SARIF presenter, a pure function over a Report value
(ARCHITECTURE.ARCH-ADHERENCE.md, Mechanism > Findings and explanations:
one SARIF rule per check, one result per finding, the identity as the
fingerprint, provenance and kind as properties, notices as
notifications), validated against the official SARIF 2.1.0 schema."""

from __future__ import annotations

import json

from adherence.cli.presenters.sarif import FINGERPRINT, report_sarif

from adherence.domain.qualities import CATALOG
from adherence.domain.report import Report
from tests.json_schema import sarif_violations
from tests.report_kit import DONE, EXEMPT, HOSTILE, NOT_KEPT, REMOVED, REPORT, STUB


def _run(report: Report = REPORT) -> dict[str, object]:
    document = json.loads(report_sarif(report, NOT_KEPT))
    (run,) = document["runs"]
    assert isinstance(run, dict)
    return run


def test_report_sarif_conforms_to_the_sarif_schema() -> None:
    """Given a judged report with findings, a removal, notices and coverage,
    When it is presented as SARIF, Then the document conforms to the
    official SARIF 2.1.0 schema."""
    document = json.loads(report_sarif(REPORT, NOT_KEPT))

    assert document["version"] == "2.1.0"
    assert sarif_violations(document) == []


def test_report_sarif_has_one_rule_per_check() -> None:
    """Given any report, When it is presented as SARIF, Then the driver
    carries one rule per check of the catalog, each naming its quality and
    kind, and each result points at its check's rule."""
    run = _run()

    rules = run["tool"]["driver"]["rules"]  # type: ignore[index]
    assert [r["name"] for r in rules] == [c.name for c in CATALOG]
    assert len({r["id"] for r in rules}) == len(CATALOG)
    stub = next(r for r in rules if r["name"] == "Stub")
    assert stub["properties"] == {"quality": "Complete", "kind": "rule"}
    for result in run["results"]:  # type: ignore[attr-defined]
        assert rules[result["ruleIndex"]]["id"] == result["ruleId"]


def test_report_sarif_has_one_result_per_finding_fingerprinted_by_identity() -> None:
    """Given a report's findings, When it is presented as SARIF, Then each is
    one result at its location, its identity the fingerprint, its
    provenance and kind properties, a judged one's confidence beside them,
    and the evidence carried as data."""
    run = _run()

    results = run["results"]
    assert isinstance(results, list)
    assert [r["partialFingerprints"][FINGERPRINT] for r in results] == [
        f.identity for f in (STUB, DONE, EXEMPT)
    ]
    stub, done, _exempt = results
    assert stub["properties"]["provenance"] == "introduced"
    assert stub["properties"]["kind"] == "rule"
    assert stub["level"] == "error"
    assert done["properties"]["provenance"] == "existing"
    assert done["properties"]["kind"] == "judged"
    assert done["properties"]["confidence"] == DONE.confidence
    assert done["level"] == "warning"
    (location,) = stub["locations"]
    physical = location["physicalLocation"]
    assert physical["artifactLocation"]["uri"] == "src/app/domain/rules.py"
    assert physical["region"]["startLine"] == 4
    assert physical["region"]["snippet"]["text"] == HOSTILE


def test_report_sarif_marks_an_exempt_finding_suppressed_with_its_reason() -> None:
    """Given a finding an exemption silences, When it is presented as SARIF,
    Then its result is suppressed by the declaration, with the reason."""
    (exempt,) = [r for r in _run()["results"] if r.get("suppressions")]  # type: ignore[attr-defined]

    assert exempt["partialFingerprints"][FINGERPRINT] == EXEMPT.identity
    assert exempt["suppressions"] == [
        {"kind": "external", "justification": EXEMPT.exempt}
    ]


def test_report_sarif_carries_notices_and_coverage_as_notifications() -> None:
    """Given notices, coverage and a report not kept, When the report is
    presented as SARIF, Then each is a notification of the invocation, and
    the verdict, its reasons and the removed findings ride on the run."""
    run = _run()

    (invocation,) = run["invocations"]  # type: ignore[misc]
    texts = [n["message"]["text"] for n in invocation["toolExecutionNotifications"]]
    assert "adherence.toml: an exemption the change adds is inert" in texts
    assert "the report was not kept: disk full" in texts
    assert any("did not finish before the deadline" in t for t in texts)
    assert invocation["executionSuccessful"] is True
    properties = run["properties"]
    assert properties["verdict"] == "lowered"  # type: ignore[index]
    assert properties["reasons"] == list(REPORT.reasons)  # type: ignore[index]
    assert [r["identity"] for r in properties["removed"]] == [REMOVED.identity]  # type: ignore[index]


def test_report_sarif_of_a_run_that_did_not_run_is_an_unsuccessful_invocation() -> None:
    """Given a report the suite could not perform, When it is presented as
    SARIF, Then it has no result, the invocation is unsuccessful with the
    reason as an error, the verdict is not run, and it still conforms."""
    report = Report.not_run("adherence.toml: line 3: bad")
    document = json.loads(report_sarif(report))
    (run,) = document["runs"]

    assert run["results"] == []
    (invocation,) = run["invocations"]
    assert invocation["executionSuccessful"] is False
    (notification,) = invocation["toolExecutionNotifications"]
    assert notification["level"] == "error"
    assert "line 3: bad" in notification["message"]["text"]
    assert sarif_violations(document) == []
