"""The judged checks and the judged parts of the rule-and-judged checks,
driven through `measure` with a fake behind every port and the judge
scripted per question id (DESIGN.ARCH-ADHERENCE.md, Behaviors;
ARCHITECTURE.ARCH-ADHERENCE.md, Use-case surface and Facts and judgements
told apart). Canned decisions sit at, above and below each threshold and
inside its band; the unit tier never loads weights or calls the network.
"""

from __future__ import annotations

import pytest

from adherence.adapters.fakes import FakeDecision
from adherence.cli.presenters.json_report import report_document
from adherence.domain.deadline import TimedOut
from adherence.domain.finding import Finding
from adherence.domain.model import (
    Body,
    CodeModel,
    Definition,
    ImportEdge,
    Layer,
)
from adherence.domain.qualities import CheckKind
from adherence.domain.questions import (
    TWO_JOBS,
    BandThreshold,
    ThresholdPolicy,
    Unavailable,
)
from adherence.domain.report import Report
from tests.facts_kit import FS, ROOT, RULES, TEST, USE, function
from tests.measure_kit import measure_with

# Provisional entries for the tests alone; the shipped ones are the
# composition root's, chosen from adherence/evals/.
BAND = BandThreshold(finding_at=0.8, pass_below=0.3)
FILES = {path: b"x\n" * 30 for path in (RULES, USE, FS, ROOT, TEST)}


def _of(report: Report, check: str) -> list[Finding]:
    return [f for f in report.findings if f.check.name == check]


def _yes(p: float) -> dict[str, float]:
    return {"yes": p, "no": 1.0 - p}


def _bodied(definition: Definition, text: str) -> Definition:
    return Definition(
        definition.unit,
        definition.signature,
        Body(text, (), ()),
        definition.bases,
        definition.decorators,
        definition.parent,
        definition.nested,
    )


# --- A unit doing two jobs is found ------------------------------------------------


@pytest.mark.parametrize(("yes", "found"), [(0.8, True), (0.95, True), (0.79, False)])
def test_measure_unit_doing_two_jobs_above_its_threshold_is_found(
    yes: float, found: bool
) -> None:
    """Given a domain function the judge says does two jobs with yes at,
    above or just below the threshold, and an application function it says
    does one, When Two jobs runs, Then a judged finding names the unit and
    the jobs, with its confidence, only at or above the threshold."""
    definitions = [
        _bodied(function(RULES, "price", 1, end=5), "total = fetch()\nsave(total)"),
        function(USE, "close_order", 1, end=5),
    ]
    judge = FakeDecision(
        {TWO_JOBS.id: _yes(0.1)}, per_symbol={"price": {TWO_JOBS.id: _yes(yes)}}
    )

    report = measure_with(
        FILES,
        CodeModel(definitions=tuple(definitions)),
        judge=judge,
        thresholds=ThresholdPolicy({TWO_JOBS.id: BAND}),
    )

    assert "Two jobs" in [c.name for c in report.ran]
    findings = _of(report, "Two jobs")
    if not found:
        assert findings == []
        return
    (finding,) = findings
    assert finding.unit.symbol == "price"
    assert finding.kind is CheckKind.JUDGED
    assert finding.confidence == pytest.approx(yes)
    assert finding.layer is Layer.DOMAIN
    assert "rules" in finding.subject and "workflow" in finding.subject


def test_measure_two_jobs_asks_about_rules_workflow_and_wiring_units_only() -> None:
    """Given functions in the domain, application, composition-root, adapters
    and test layers, When Two jobs runs, Then the judge is asked about the
    first three, each unit's text with its declared layer as the state, and
    never about an adapter or a test."""
    definitions = [
        _bodied(function(RULES, "price", 1, end=5), "return order.total"),
        function(USE, "close_order", 1, end=5),
        function(ROOT, "build", 1, end=5),
        function(FS, "read", 1, end=5),
        function(TEST, "test_close", 1, end=5),
    ]
    judge = FakeDecision({TWO_JOBS.id: _yes(0.1)})

    measure_with(
        FILES,
        CodeModel(definitions=tuple(definitions)),
        judge=judge,
        thresholds=ThresholdPolicy({TWO_JOBS.id: BAND}),
    )

    asked = {
        state.unit.symbol: (state, schema)
        for state, schema in judge.asked
        if any(q.id == TWO_JOBS.id for q in schema.questions.values())
    }
    assert set(asked) == {"price", "close_order", "build"}
    state, schema = asked["price"]
    assert "return order.total" in state.text
    assert any("domain" in context for context in state.context.values())


# --- An abstention is inconclusive (the measure half) ------------------------------


def test_measure_answer_inside_the_band_is_an_abstention_on_the_report() -> None:
    """Given a unit the judge answers inside the abstention band, When it is
    measured, Then the report carries an abstention naming the check, the
    unit, the question and its confidence -- not a finding and not a pass --
    and the JSON document prints it. judge_change reads an abstention on a
    touched unit as inconclusive, never lowered."""
    judge = FakeDecision({TWO_JOBS.id: _yes(0.5)})

    report = measure_with(
        FILES,
        CodeModel(definitions=(function(RULES, "price", 1, end=5),)),
        judge=judge,
        thresholds=ThresholdPolicy({TWO_JOBS.id: BAND}),
    )

    assert _of(report, "Two jobs") == []
    (abstention,) = report.abstentions
    assert abstention.check.name == "Two jobs"
    assert abstention.unit.symbol == "price"
    assert abstention.question == TWO_JOBS.id
    assert abstention.confidence == pytest.approx(0.5)
    assert not any(c.check == "Two jobs" for c in report.coverage)
    printed = report_document(report)["abstentions"]
    assert printed == [
        {
            "quality": "Layered",
            "check": "Two jobs",
            "question": TWO_JOBS.id,
            "path": RULES,
            "symbol": "price",
            "subject": abstention.subject,
            "confidence": pytest.approx(0.5),
        }
    ]


def test_measure_judged_finding_prints_its_kind_and_confidence() -> None:
    """Given a judged finding, When the report is printed as JSON, Then the
    finding says it is judged and carries its confidence (G2), where a rule
    finding carries none."""
    judge = FakeDecision({TWO_JOBS.id: _yes(0.9)})

    report = measure_with(
        FILES,
        CodeModel(definitions=(function(RULES, "price", 1, end=5),)),
        judge=judge,
        thresholds=ThresholdPolicy({TWO_JOBS.id: BAND}),
    )

    layered = next(
        q for q in report_document(report)["qualities"] if q["quality"] == "Layered"
    )
    (printed,) = [f for f in layered["findings"] if f["check"] == "Two jobs"]
    assert printed["kind"] == "judged"
    assert printed["confidence"] == pytest.approx(0.9)


# --- An unavailable judge is inconclusive, never raised (the measure half) --------


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (Unavailable("the door refused the connection"), "door refused"),
        (TimedOut("ask the judge"), "timed out"),
    ],
)
def test_measure_with_no_judge_reachable_reports_every_question_as_coverage(
    failure: Unavailable | TimedOut, reason: str
) -> None:
    """Given a judge that is unavailable or past the deadline and two units
    with questions, beside a rule finding, When measured, Then every
    question is coverage naming the check, the unit and why; no judged
    finding, pass or abstention is reported, the judged check is not among
    the checks that ran, the judge is not asked again after the first
    failure, and the rule finding stands. judge_change reads this coverage
    as inconclusive and counts no judged finding as removed."""
    definitions = (
        function(RULES, "price", 1, end=5),
        function(USE, "close_order", 1, end=5),
    )
    leak = ImportEdge(RULES, "requests", 2, "import requests", None)
    judge = FakeDecision(failure)

    report = measure_with(
        FILES,
        CodeModel(definitions=definitions, imports=(leak,)),
        judge=judge,
        thresholds=ThresholdPolicy({TWO_JOBS.id: BAND}),
    )

    covered = sorted(
        (c.path or "", c.reason) for c in report.coverage if c.check == "Two jobs"
    )
    assert [path for path, _ in covered] == sorted([RULES, USE])
    assert all(reason in why and TWO_JOBS.id in why for _, why in covered)
    assert _of(report, "Two jobs") == [] and report.abstentions == ()
    assert "Two jobs" not in [c.name for c in report.ran]
    assert len(judge.asked) == 1
    assert [f.unit.path for f in _of(report, "Grep")] == [RULES]
