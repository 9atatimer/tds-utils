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
from adherence.adapters.no_judge import NoJudge
from adherence.cli.presenters.json_report import report_document
from adherence.domain.deadline import TimedOut
from adherence.domain.finding import Finding
from adherence.domain.model import (
    Assertion,
    Body,
    Call,
    CodeModel,
    Conditional,
    Definition,
    ImportEdge,
    Layer,
    Reference,
    ReferenceKind,
    Target,
    TestCase,
    Write,
)
from adherence.domain.parameters import Limits
from adherence.domain.qualities import CheckKind
from adherence.domain.questions import (
    DOES_IO,
    HAND_ROLLED_ID,
    IMPLEMENTED,
    INVARIANT_BROKEN,
    NONE,
    RULES_ELSEWHERE,
    SAME_CONCEPT,
    SCATTERED_POLICY,
    THEN_ASSERTED,
    TWO_JOBS,
    BandThreshold,
    ChoiceThreshold,
    Rejected,
    ThresholdPolicy,
    Unavailable,
)
from adherence.domain.records import (
    Behavior,
    DesignRecords,
    Radar,
    RadarEntry,
    RecordsUnavailable,
    Ring,
    SurfaceRow,
    Term,
)
from adherence.domain.report import Report
from tests.facts_kit import (
    FS,
    ROOT,
    RULES,
    STORE,
    TEST,
    USE,
    field,
    function,
    port,
    type_,
    value,
)
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


def _stubbed(definition: Definition) -> Definition:
    return Definition(
        definition.unit,
        definition.signature,
        Body("...", ("...",), ()),
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


def test_measure_judged_pass_is_on_the_report_with_its_confidence() -> None:
    """Given a unit the judge answers below the pass threshold, When it is
    measured, Then the report carries a pass naming the check, the unit,
    the question and its confidence -- not a finding and not an
    abstention -- and the JSON document prints it."""
    judge = FakeDecision({TWO_JOBS.id: _yes(0.1)})

    report = measure_with(
        FILES,
        CodeModel(definitions=(function(RULES, "price", 1, end=5),)),
        judge=judge,
        thresholds=ThresholdPolicy({TWO_JOBS.id: BAND}),
    )

    assert _of(report, "Two jobs") == [] and report.abstentions == ()
    (passed,) = [p for p in report.passes if p.check.name == "Two jobs"]
    assert passed.unit.symbol == "price"
    assert passed.question == TWO_JOBS.id
    assert passed.confidence == pytest.approx(0.9)
    printed = report_document(report)["passes"]
    assert {
        "quality": "Layered",
        "check": "Two jobs",
        "question": TWO_JOBS.id,
        "path": RULES,
        "symbol": "price",
        "confidence": pytest.approx(0.9),
    } in printed


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


# --- An exhausted judged-check budget is inconclusive (the measure half) ----------


def test_measure_past_the_judged_budget_reports_the_questions_not_asked() -> None:
    """Given three units with two questions each (Two jobs and Done) and a
    judged-check budget of four, When measured, Then the judge is asked
    about the first two units only and coverage names each of the third
    unit's questions as not asked for the budget -- never a pass.
    judge_change reads it, on a touched unit, as inconclusive at best."""
    definitions = (
        function(RULES, "price", 1, end=5),
        function(RULES, "discount", 7, end=9),
        function(USE, "close_order", 1, end=5),
    )
    judge = FakeDecision({TWO_JOBS.id: _yes(0.1), IMPLEMENTED.id: _yes(0.9)})

    report = measure_with(
        FILES,
        CodeModel(definitions=definitions),
        judge=judge,
        thresholds=ThresholdPolicy({TWO_JOBS.id: BAND, IMPLEMENTED.id: BAND}),
        limits=Limits(evidence_bound=200, judged_budget=4),
    )

    assert [state.unit.symbol for state, _ in judge.asked] == ["price", "discount"]
    unasked = [c for c in report.coverage if "budget" in c.reason]
    assert sorted(c.check or "" for c in unasked) == ["Done", "Two jobs"]
    assert all(c.path == USE and "close_order" in c.reason for c in unasked)
    assert {TWO_JOBS.id, IMPLEMENTED.id} == {
        q for q in (TWO_JOBS.id, IMPLEMENTED.id) for c in unasked if q in c.reason
    }


def test_measure_with_no_judged_budget_asks_nothing() -> None:
    """Given a unit with a question and a budget of none, When measured, Then
    the judge is never called and the question is coverage."""
    judge = FakeDecision({TWO_JOBS.id: _yes(0.95)})

    report = measure_with(
        FILES,
        CodeModel(definitions=(function(RULES, "price", 1, end=5),)),
        judge=judge,
        thresholds=ThresholdPolicy({TWO_JOBS.id: BAND}),
        limits=Limits(evidence_bound=200, judged_budget=0),
    )

    assert judge.asked == []
    assert _of(report, "Two jobs") == []
    assert [c.path for c in report.coverage if c.check == "Two jobs"] == [RULES]


def test_measure_with_no_judge_and_no_budget_names_the_judge() -> None:
    """Given the hook stage's shape -- no judge bound and a budget of none --
    and a unit with a question, When measured, Then the question is
    coverage naming why there is no judge, never the budget."""
    report = measure_with(
        FILES,
        CodeModel(definitions=(function(RULES, "price", 1, end=5),)),
        judge=NoJudge("the hook asks no judge"),
        thresholds=ThresholdPolicy({TWO_JOBS.id: BAND}),
        limits=Limits(evidence_bound=200, judged_budget=0),
    )

    reasons = [c.reason for c in report.coverage if c.check == "Two jobs"]
    assert len(reasons) == 1
    assert "the hook asks no judge" in reasons[0]
    assert "budget" not in reasons[0]


# --- A port in a rule is found (judged part) ---------------------------------------


@pytest.mark.parametrize(("yes", "found"), [(0.8, True), (0.9, True), (0.79, False)])
def test_measure_domain_function_taking_a_callable_that_does_io_is_found(
    yes: float, found: bool
) -> None:
    """Given a domain function taking a callable, called from a use case, and
    the judge's yes that the callable does I/O at, above or just below the
    threshold, When Purity's judged part runs, Then a judged finding names
    the function and the parameter, with its confidence, only at or above
    the threshold; the judge is given the parameter and the call site."""
    definitions = (
        function(RULES, "total", 1, (value("fetch", "Callable[[str], bytes]"),)),
        function(USE, "close_order", 1, end=5),
    )
    call = Call(
        USE, 3, "close_order", "total", Target("app.domain.total", RULES, "total")
    )
    judge = FakeDecision({DOES_IO.id: _yes(yes), TWO_JOBS.id: _yes(0.1)})

    report = measure_with(
        FILES,
        CodeModel(definitions=definitions, calls=(call,)),
        judge=judge,
        thresholds=ThresholdPolicy({DOES_IO.id: BAND, TWO_JOBS.id: BAND}),
    )

    findings = _of(report, "Purity")
    asked = [
        (state, key)
        for state, schema in judge.asked
        for key, q in schema.questions.items()
        if q.id == DOES_IO.id
    ]
    ((state, key),) = asked
    assert state.unit.symbol == "total"
    assert "fetch" in state.context[key] and "close_order" in state.context[key]
    if not found:
        assert findings == []
        return
    (finding,) = findings
    assert finding.kind is CheckKind.JUDGED
    assert finding.confidence == pytest.approx(yes)
    assert finding.unit.symbol == "total"
    assert "total" in finding.subject and "fetch" in finding.subject


# --- Two spellings of one concept are found -----------------------------------------

DESIGN = "docs/design/DESIGN.APP.md"
GLOSSARY = DesignRecords(
    domain_language=(Term("Order", DESIGN, 40), Term("Ledger entry", DESIGN, 41))
)


@pytest.mark.parametrize(("yes", "found"), [(0.8, True), (0.85, True), (0.79, False)])
def test_measure_two_spellings_of_one_concept_are_found(
    yes: float, found: bool
) -> None:
    """Given a domain type the Domain Language defines (Order), an undefined
    domain type sharing a word with it (OrderRecord) that a use case takes,
    and undefined nouns sharing no word with a defined one, When Language's
    judged part runs with the judge's yes at, above or just below the
    threshold, Then only the pair that shares a word is asked about, with
    both nouns' definitions and uses as its data, and a judged finding names
    both nouns, with its confidence, only at or above the threshold."""
    definitions = (
        type_(RULES, "Order", 1),
        type_(RULES, "OrderRecord", 5),
        type_(RULES, "Invoice", 9),
        function(USE, "close", 1, (value("order", "OrderRecord"),), returns="Receipt"),
    )
    judge = FakeDecision({SAME_CONCEPT.id: _yes(yes), TWO_JOBS.id: _yes(0.1)})

    report = measure_with(
        FILES,
        CodeModel(definitions=definitions),
        records=GLOSSARY,
        judge=judge,
        thresholds=ThresholdPolicy({SAME_CONCEPT.id: BAND, TWO_JOBS.id: BAND}),
    )

    asked = [
        (state, key)
        for state, schema in judge.asked
        for key, q in schema.questions.items()
        if q.id == SAME_CONCEPT.id
    ]
    ((state, key),) = asked
    assert state.unit.symbol == "OrderRecord"
    assert "Order" in state.context[key] and "close" in state.context[key]
    judged = [f for f in _of(report, "Language") if f.kind is CheckKind.JUDGED]
    if not found:
        assert judged == []
        return
    (finding,) = judged
    assert finding.confidence == pytest.approx(yes)
    assert finding.subject.startswith("OrderRecord and Order:")


# --- A hidden policy is found --------------------------------------------------------


@pytest.mark.parametrize(("yes", "found"), [(0.8, True), (0.99, True), (0.79, False)])
def test_measure_choice_spread_across_conditionals_is_found(
    yes: float, found: bool
) -> None:
    """Given two units in the core branching on one attribute (order.kind),
    a discriminant only one unit branches on, a bare local name, and a test
    branching on the same attribute, When Decision runs with the judge's yes
    at, above or just below the threshold, Then only the shared attribute
    is asked about, the conditionals and their units as the data, and a
    judged finding names the conditionals and the discriminant, with its
    confidence, only at or above the threshold."""
    definitions = (
        function(RULES, "price", 1, end=5),
        function(RULES, "discount", 7, end=9),
        function(USE, "close_order", 1, end=5),
        function(TEST, "test_close", 1, end=5),
    )
    conditionals = (
        Conditional(RULES, 2, "price", "order.kind"),
        Conditional(RULES, 8, "discount", "order.total"),
        Conditional(USE, 3, "close_order", "order.kind"),
        Conditional(USE, 4, "close_order", "x"),
        Conditional(TEST, 2, "test_close", "order.kind"),
    )
    judge = FakeDecision({SCATTERED_POLICY.id: _yes(yes), TWO_JOBS.id: _yes(0.1)})

    report = measure_with(
        FILES,
        CodeModel(definitions=definitions, conditionals=conditionals),
        judge=judge,
        thresholds=ThresholdPolicy({SCATTERED_POLICY.id: BAND, TWO_JOBS.id: BAND}),
    )

    assert "Decision" in [c.name for c in report.ran]
    asked = [
        (state, key)
        for state, schema in judge.asked
        for key, q in schema.questions.items()
        if q.id == SCATTERED_POLICY.id
    ]
    ((state, key),) = asked
    assert state.unit.symbol == "price"
    assert (
        "close_order" in state.context[key] and "test_close" not in state.context[key]
    )
    findings = _of(report, "Decision")
    if not found:
        assert findings == []
        return
    (finding,) = findings
    assert finding.confidence == pytest.approx(yes)
    assert finding.kind is CheckKind.JUDGED
    assert "order.kind" in finding.subject
    assert "price" in finding.subject and "close_order" in finding.subject


# --- A write that breaks an invariant is found ------------------------------------


@pytest.mark.parametrize(("yes", "found"), [(0.8, True), (0.9, True), (0.79, False)])
def test_measure_foreign_write_that_breaks_an_invariant_is_found(
    yes: float, found: bool
) -> None:
    """Given a use case writing a domain type's field outside the type, When
    Boundary's judged part runs with the judge's yes at, above or just below
    the threshold, Then the rule finding on the write stands, the judge is
    given the writer, the owning type and the write, and a judged finding
    names the write and the invariant at risk, with its confidence and an
    identity of its own, only at or above the threshold."""
    definitions = (
        _bodied(type_(RULES, "Order", 1, end=4), "status: str\ntotal: int"),
        function(USE, "close", 1, (value("order", "Order"),), end=4),
    )
    members = (field(RULES, "Order", "status", 2), field(RULES, "Order", "total", 3))
    writes = (Write(USE, 2, "close", "order", "status"),)
    judge = FakeDecision({INVARIANT_BROKEN.id: _yes(yes), TWO_JOBS.id: _yes(0.1)})

    report = measure_with(
        FILES,
        CodeModel(definitions=definitions, members=members, writes=writes),
        judge=judge,
        thresholds=ThresholdPolicy({INVARIANT_BROKEN.id: BAND, TWO_JOBS.id: BAND}),
    )

    rule = [f for f in _of(report, "Boundary") if f.kind is CheckKind.RULE]
    judged = [f for f in _of(report, "Boundary") if f.kind is CheckKind.JUDGED]
    assert len(rule) == 1
    ((state, key),) = [
        (state, key)
        for state, schema in judge.asked
        for key, q in schema.questions.items()
        if q.id == INVARIANT_BROKEN.id
    ]
    assert state.unit.symbol == "close"
    assert "status: str" in state.context[key] and "order.status" in state.context[key]
    if not found:
        assert judged == []
        return
    (finding,) = judged
    assert finding.confidence == pytest.approx(yes)
    assert "Order.status" in finding.subject and "invariant" in finding.subject
    assert finding.identity != rule[0].identity


# --- An anemic type is found (judged part) ------------------------------------------


@pytest.mark.parametrize(("yes", "found"), [(0.8, True), (0.97, True), (0.79, False)])
def test_measure_all_fields_type_whose_rules_live_elsewhere_is_found(
    yes: float, found: bool
) -> None:
    """Given a domain type that is all fields, a use case computing over its
    fields through a parameter of that type, and another all-fields type
    nothing computes over, When Anemic's judged part runs with the judge's
    yes at, above or just below the threshold, Then only the first type is
    asked about, with the computing unit as the data, and a judged finding
    names the type and the unit holding its rules, with its confidence, only
    at or above the threshold."""
    definitions = (
        _bodied(type_(RULES, "Receipt", 1, end=3), "number: int\ntotal: int"),
        type_(RULES, "Money", 5, end=7),
        _bodied(
            function(USE, "issue", 1, (value("receipt", "Receipt"),), end=4),
            "return receipt.total * 2",
        ),
    )
    members = (
        field(RULES, "Receipt", "number", 2),
        field(RULES, "Receipt", "total", 3),
        field(RULES, "Money", "cents", 6),
    )
    uses = (Reference(USE, 2, "issue", ReferenceKind.NAME, "receipt.total"),)
    judge = FakeDecision({RULES_ELSEWHERE.id: _yes(yes), TWO_JOBS.id: _yes(0.1)})

    report = measure_with(
        FILES,
        CodeModel(definitions=definitions, members=members, references=uses),
        judge=judge,
        thresholds=ThresholdPolicy({RULES_ELSEWHERE.id: BAND, TWO_JOBS.id: BAND}),
    )

    ((state, key),) = [
        (state, key)
        for state, schema in judge.asked
        for key, q in schema.questions.items()
        if q.id == RULES_ELSEWHERE.id
    ]
    assert state.unit.symbol == "Receipt"
    assert "receipt.total * 2" in state.context[key]
    assert not any(c.check == "Anemic" for c in report.coverage)
    findings = _of(report, "Anemic")
    if not found:
        assert findings == []
        return
    (finding,) = findings
    assert finding.kind is CheckKind.JUDGED
    assert finding.confidence == pytest.approx(yes)
    assert "Receipt" in finding.subject and "issue" in finding.subject


# --- A test that skips the Then is found ----------------------------------------------

CLOSED = "An order is closed"
SURFACE = "docs/design/ARCHITECTURE.APP.md"
SCENARIO = "Given an open order, When it is closed, Then the store holds it closed"
SURFACED = DesignRecords(
    behaviors=(
        Behavior(CLOSED, SCENARIO, DESIGN, 9),
        Behavior("An order is priced", "Given a, When b, Then c", DESIGN, 10),
    ),
    surface=(
        SurfaceRow(CLOSED, "close_order", "docs/design/ARCHITECTURE.APP.md", 12),
        SurfaceRow(
            "An order is priced", "price", "docs/design/ARCHITECTURE.APP.md", 13
        ),
    ),
)


def _not_asserted(p: float) -> dict[str, float]:
    return {"not asserted": p, "partly": 1.0 - p, "fully": 0.0}


@pytest.mark.parametrize(("mass", "found"), [(0.8, True), (0.9, True), (0.79, False)])
def test_measure_kept_test_that_skips_the_then_is_found(
    mass: float, found: bool
) -> None:
    """Given a design behavior whose use case a test calls, and a behavior
    whose use case no test calls, When Then asserted runs with the judge's
    mass on `not asserted` at, above or just below the threshold, Then only
    the kept test is asked about, its body as the state and the row's Then
    as the data, and a judged finding names the test and the behavior, with
    its confidence, only at or above the threshold."""
    definitions = (
        function(USE, "close_order", 1, end=5),
        function(RULES, "price", 1, end=5),
        _bodied(function(TEST, "test_close", 1, end=4), "close_order(order)"),
    )
    calls = (
        Call(
            TEST,
            2,
            "test_close",
            "close_order",
            Target("close_order", USE, "close_order"),
        ),
    )
    cases = (TestCase(TEST, "test_close", 1, ("close_order",), (Assertion("order"),)),)
    judge = FakeDecision(
        {THEN_ASSERTED.id: _not_asserted(mass), TWO_JOBS.id: _yes(0.1)}
    )

    report = measure_with(
        FILES,
        CodeModel(definitions=definitions, calls=calls, test_cases=cases),
        records=SURFACED,
        judge=judge,
        thresholds=ThresholdPolicy({THEN_ASSERTED.id: BAND, TWO_JOBS.id: BAND}),
    )

    assert "Then asserted" in [c.name for c in report.ran]
    ((state, key),) = [
        (state, key)
        for state, schema in judge.asked
        for key, q in schema.questions.items()
        if q.id == THEN_ASSERTED.id
    ]
    assert state.unit.symbol == "test_close"
    assert "close_order(order)" in state.text
    assert "Then the store holds it closed" in state.context[key]
    findings = _of(report, "Then asserted")
    if not found:
        assert findings == []
        return
    (finding,) = findings
    assert finding.kind is CheckKind.JUDGED
    assert finding.confidence == pytest.approx(mass)
    assert "test_close" in finding.subject and CLOSED in finding.subject


# --- An unfinished unit is found ------------------------------------------------------


@pytest.mark.parametrize(("no", "found"), [(0.8, True), (0.88, True), (0.79, False)])
def test_measure_unit_whose_body_does_not_do_what_it_claims_is_found(
    no: float, found: bool
) -> None:
    """Given a domain function whose docstring claims more than its body
    does, functions that do what they claim, a stub (Stub's), a port's
    declared method and a test, When Done runs with the judge's no at, above
    or just below the threshold, Then only the non-test, non-stub,
    non-declaration functions are asked about, each its name, docstring and
    body, and a judged finding names the unfinished unit, with its
    confidence, only at or above the threshold."""
    definitions = (
        _bodied(
            function(RULES, "price", 1, end=4),
            '"""Price the order, with tax and discounts."""\nreturn 0',
        ),
        function(USE, "close_order", 1, end=5),
        function(FS, "read", 1, end=5),
        _stubbed(function(RULES, "later", 7, end=8)),
        *port(STORE, "Store", 1),
        function(TEST, "test_close", 1, end=4),
    )
    judge = FakeDecision(
        {IMPLEMENTED.id: _yes(0.95), TWO_JOBS.id: _yes(0.1)},
        per_symbol={"price": {IMPLEMENTED.id: _yes(1.0 - no)}},
    )

    report = measure_with(
        {**FILES, STORE: b"x\n" * 9},
        CodeModel(definitions=definitions),
        judge=judge,
        thresholds=ThresholdPolicy({IMPLEMENTED.id: BAND, TWO_JOBS.id: BAND}),
    )

    assert "Done" in [c.name for c in report.ran]
    asked = {
        state.unit.symbol: state
        for state, schema in judge.asked
        if any(q.id == IMPLEMENTED.id for q in schema.questions.values())
    }
    assert set(asked) == {"price", "close_order", "read"}
    assert "with tax and discounts" in asked["price"].text
    findings = _of(report, "Done")
    if not found:
        assert findings == []
        return
    (finding,) = findings
    assert finding.kind is CheckKind.JUDGED
    assert finding.confidence == pytest.approx(no)
    assert finding.unit.symbol == "price" and "price" in finding.subject


# --- A hand-rolled primitive is found -------------------------------------------------

RADAR = Radar(
    entries=(
        RadarEntry("markdown-it-py", Ring.ADOPT, "lmde/TECH_RADAR.md", 5),
        RadarEntry("click", Ring.ADOPT, "lmde/TECH_RADAR.md", 6),
        RadarEntry("lizard", Ring.TRIAL, "lmde/TECH_RADAR.md", 7),
        RadarEntry("left-pad", Ring.HOLD, "lmde/TECH_RADAR.md", 8),
    )
)


@pytest.mark.parametrize(("p", "found"), [(0.8, True), (0.9, True), (0.79, False)])
def test_measure_primitive_written_by_hand_where_the_radar_adopts_one_is_found(
    p: float, found: bool
) -> None:
    """Given a function parsing markdown tables by hand and a radar adopting
    markdown-it-py and click (a Trial and a Hold entry beside them), When
    Hand-rolled runs with the judge's most likely option, markdown-it-py,
    at, above or just below the threshold, Then the question's options are
    the Adopt entries by their keys and none, and a judged finding names
    the unit and the library, with its confidence, only at or above the
    threshold."""
    definitions = (
        _bodied(function(FS, "parse_table", 1, end=9), "for line in text: ..."),
    )
    judge = FakeDecision(
        {
            HAND_ROLLED_ID: {"lib_1": p, "lib_2": 0.0, NONE: 1.0 - p},
            TWO_JOBS.id: _yes(0.1),
            IMPLEMENTED.id: _yes(0.9),
        }
    )

    report = measure_with(
        FILES,
        CodeModel(definitions=definitions),
        radar=RADAR,
        judge=judge,
        thresholds=ThresholdPolicy(
            {HAND_ROLLED_ID: ChoiceThreshold(at=0.8), IMPLEMENTED.id: BAND}
        ),
    )

    assert "Hand-rolled" in [c.name for c in report.ran]
    ((question,),) = [
        [q for q in schema.questions.values() if q.id == HAND_ROLLED_ID]
        for _, schema in judge.asked
    ]
    assert question.options == ("lib_1", "lib_2", NONE)
    findings = _of(report, "Hand-rolled")
    if not found:
        assert findings == []
        return
    (finding,) = findings
    assert finding.kind is CheckKind.JUDGED
    assert finding.confidence == pytest.approx(p)
    assert "parse_table" in finding.subject and "markdown-it-py" in finding.subject


def test_measure_hand_rolled_without_a_radar_is_coverage() -> None:
    """Given no radar the declaration names, When Hand-rolled runs, Then it is
    coverage naming why, asks nothing, and is not among the checks that ran."""
    judge = FakeDecision({TWO_JOBS.id: _yes(0.1), IMPLEMENTED.id: _yes(0.9)})

    report = measure_with(
        FILES,
        CodeModel(definitions=(function(FS, "parse_table", 1, end=9),)),
        radar=RecordsUnavailable("no radar at this target"),
        judge=judge,
    )

    assert "Hand-rolled" not in [c.name for c in report.ran]
    assert [c.reason for c in report.coverage if c.check == "Hand-rolled"] == [
        "no radar at this target"
    ]
    assert not any(
        q.id == HAND_ROLLED_ID
        for _, schema in judge.asked
        for q in schema.questions.values()
    )


def test_measure_call_the_judge_rejects_is_coverage_and_the_rest_are_asked() -> None:
    """Given a judge that rejects what it is sent, When two units are
    measured, Then each call's questions are coverage naming the rejection,
    and a rejection, being about one call, does not stop the next."""
    judge = FakeDecision(Rejected("the state is too large"))

    report = measure_with(
        FILES,
        CodeModel(
            definitions=(
                function(RULES, "price", 1, end=5),
                function(USE, "close_order", 1, end=5),
            )
        ),
        judge=judge,
        thresholds=ThresholdPolicy({TWO_JOBS.id: BAND}),
    )

    assert len(judge.asked) == 2
    rejected = [c for c in report.coverage if c.check == "Two jobs"]
    assert sorted(c.path or "" for c in rejected) == sorted([RULES, USE])
    assert all("too large" in c.reason for c in rejected)
