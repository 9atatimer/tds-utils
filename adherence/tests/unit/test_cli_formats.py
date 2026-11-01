"""`adhere measure` and `adhere judge` choose their presenter from one
option (ARCHITECTURE.ARCH-ADHERENCE.md, Module map: cli/main.py, the
presenters for terminal, JSON, SARIF and PR summary): the terminal by
default, `--format json|sarif|summary` otherwise, `--json` kept as JSON's
short form for the ci-magic toolkit line."""

from __future__ import annotations

import json
from pathlib import Path

from adherence.cli.presenters.sarif import FINGERPRINT
from tests.cli_kit import JUDGE, adhere
from tests.json_schema import sarif_violations


def test_judge_as_sarif_prints_a_conforming_log_of_the_introduced_stub(
    tmp_path: Path,
) -> None:
    """Given a head that adds a stubbed rule, When `adhere judge --format
    sarif` runs, Then it prints a SARIF 2.1.0 log that conforms, whose one
    result is the introduced Stub fingerprinted by its identity."""
    result = adhere(tmp_path, *JUDGE, "--format", "sarif")

    document = json.loads(result.output)
    assert sarif_violations(document) == []
    (run,) = document["runs"]
    (stub,) = run["results"]
    assert stub["ruleId"] == "stub"
    assert stub["properties"]["provenance"] == "introduced"
    assert stub["partialFingerprints"][FINGERPRINT]
    assert run["properties"]["verdict"] == "lowered"


def test_judge_as_summary_prints_the_job_summary(tmp_path: Path) -> None:
    """Given the same change, When `adhere judge --format summary` runs, Then
    it prints the job summary headed by the verdict."""
    result = adhere(tmp_path, *JUDGE, "--format", "summary")

    assert result.output.splitlines()[0] == "## Adherence: lowered"


def test_judge_with_no_format_prints_the_terminal_report(tmp_path: Path) -> None:
    """Given the same change, When `adhere judge` runs with no format, Then
    it prints the terminal report, the verdict first and the stub named."""
    result = adhere(tmp_path, *JUDGE)

    lines = result.output.splitlines()
    assert lines[0] == "verdict: lowered"
    assert "  introduced  Complete / Stub (rule)" in lines


def test_measure_with_no_format_prints_the_terminal_report(tmp_path: Path) -> None:
    """Given a working tree with a stubbed rule, When `adhere measure` runs
    with no format, Then it prints the terminal report of a measurement,
    which has no verdict, with the stub named."""
    result = adhere(tmp_path, "measure")

    lines = result.output.splitlines()
    assert lines[0] == "measured"
    assert "  finding  Complete / Stub (rule)" in lines


def test_measure_as_sarif_prints_a_conforming_log(tmp_path: Path) -> None:
    """Given the same working tree, When `adhere measure --format sarif`
    runs, Then the log conforms and carries no verdict."""
    result = adhere(tmp_path, "measure", "--format", "sarif")

    document = json.loads(result.output)
    assert sarif_violations(document) == []
    assert document["runs"][0]["properties"]["verdict"] is None
