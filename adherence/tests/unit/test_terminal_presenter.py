"""The terminal presenter, a pure function over a Report value
(ARCHITECTURE.ARCH-ADHERENCE.md, Seams: presenters in cli/; Security
mitigations: the code under measurement is untrusted, through the report).
Evidence, symbols and paths are author-controlled: control characters and
ANSI escapes are stripped, and no line can read as a workflow command in a
CI job's log."""

from __future__ import annotations

import unicodedata

from adherence.cli.presenters.terminal import report_text

from adherence.domain.report import Report
from tests.report_kit import NOT_KEPT, REPORT


def test_report_text_names_the_verdict_and_every_finding_with_what_fixes_it() -> None:
    """Given a judged report, When it is shown on the terminal, Then the
    verdict and why lead, and each finding names its quality, check, kind,
    provenance, unit and location; a judged one its confidence, an exempt
    one its reason; and the removed findings, notices, coverage,
    abstentions and a report not kept each appear."""
    text = report_text(REPORT, NOT_KEPT)

    lines = text.splitlines()
    assert lines[0] == "verdict: lowered"
    assert "Stub on src/app/domain/rules.py introduced" in text
    assert "introduced  Complete / Stub (rule)" in text
    assert "existing  Complete / Done (judged, confidence 0.93)" in text
    assert "src/app/domain/rules.py:4 discount" in text
    assert "exempt: the owner's reason <i>here</i>" in text
    assert "removed  Complete / Stub (rule)" in text
    assert "an exemption the change adds is inert" in text
    assert "Complexity: did not finish before the deadline" in text
    assert "abstained  Layered / Two jobs (confidence 0.60)" in text
    assert "the report was not kept: disk full" in text


def test_report_text_strips_ansi_escapes_and_control_characters() -> None:
    """Given evidence and a path carrying ANSI escapes, a carriage return, a
    newline and a bidi override, When the report is shown on the terminal,
    Then no escape sequence, control or format character survives and the
    escape's parameters do not leak as text."""
    text = report_text(REPORT, NOT_KEPT)

    for line in text.splitlines():
        assert not [ch for ch in line if unicodedata.category(ch) in {"Cc", "Cf"}]
    assert "[31m" not in text and "0;owned" not in text and "[2K" not in text
    assert "x = 1::error::forged<b>|*_[a](b)" in text


def test_report_text_never_starts_a_line_with_a_workflow_command() -> None:
    """Given author text that is a workflow command, When the report is
    shown in a CI job's log, Then no line reads as one, whatever leads it."""
    text = report_text(REPORT, NOT_KEPT)

    assert not [line for line in text.splitlines() if line.lstrip().startswith("::")]


def test_report_text_of_a_run_that_did_not_run_says_why() -> None:
    """Given a report the suite could not perform, When it is shown, Then it
    says not run and why, and nothing in it reads as a pass."""
    text = report_text(Report.not_run("adherence.toml: line 3: bad\x1b[0m"))

    assert text.splitlines()[0] == "not run: adherence.toml: line 3: bad"
    assert "held" not in text and "raised" not in text
