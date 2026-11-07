"""Design row "A judged check answers with a confidence": domain/questions
applies ThresholdPolicy by question id and stamps a confidence on the
finding, the pass and the abstention alike (ARCHITECTURE.ARCH-ADHERENCE.md,
Use-case surface; Facts and judgements told apart).

Pure values in and out, no fake: canned Decisions at, just above and just
below each threshold, inside each abstention band, for each kind of
question -- binary, choice, score -- and an uncalibrated answer, which never
meets a threshold (the decision-models skill, Testing).
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from adherence.domain.coverage import Coverage
from adherence.domain.finding import Evidence, Finding
from adherence.domain.model import Layer, Unit, UnitKind
from adherence.domain.qualities import CheckKind, catalog_check
from adherence.domain.questions import (
    HAND_ROLLED_ID,
    IMPLEMENTED,
    KIND,
    NONE,
    THEN_ASSERTED,
    Abstention,
    Ask,
    BandThreshold,
    ChoiceThreshold,
    Decision,
    Pass,
    Question,
    ThresholdPolicy,
    hand_rolled_question,
    judged,
)

UNIT = Unit("src/app/domain/rules.py", UnitKind.FUNCTION, "price", 3, 9, Layer.DOMAIN)
EVIDENCE = Evidence(UNIT.path, 3, "price")
KEY = "q.1"
POLICY = ThresholdPolicy(
    {
        KIND.id: BandThreshold(finding_at=0.8, pass_below=0.3),
        IMPLEMENTED.id: BandThreshold(finding_at=0.8, pass_below=0.3),
        HAND_ROLLED_ID: ChoiceThreshold(at=0.7),
        THEN_ASSERTED.id: BandThreshold(finding_at=0.6, pass_below=0.2),
    }
)
LIBRARIES = hand_rolled_question(2)
NAMED = {"lib_1": "markdown-it-py", "lib_2": "click"}


def _ask(question: Question, check: str = "Kind") -> Ask:
    return Ask(
        check=catalog_check(check),
        question=question,
        unit=UNIT,
        layer=Layer.DOMAIN,
        subject="price: the subject",
        evidence=EVIDENCE,
        text="def price(): ...",
        context="",
        named=NAMED if question is LIBRARIES else {},
    )


def _decide(probabilities: dict[str, float]) -> Decision:
    return Decision({KEY: probabilities})


def _binary(question: Question, yes: float) -> Finding | Pass | Abstention | Coverage:
    return judged(_ask(question), KEY, _decide({"yes": yes, "no": 1 - yes}), POLICY)


# --- binary: the probability of the failing answer -----------------------------


@pytest.mark.parametrize("yes", [0.8, 0.81, 1.0])
def test_judged_binary_at_or_above_its_threshold_is_a_finding(yes: float) -> None:
    """Given a binary question whose yes is a finding and the judge's yes at
    or above the threshold, When it is judged, Then it is a judged finding
    carrying that probability as its confidence."""
    outcome = _binary(KIND, yes)

    assert isinstance(outcome, Finding), outcome
    assert outcome.kind is CheckKind.JUDGED
    assert outcome.confidence == pytest.approx(yes)
    assert outcome.subject == "price: the subject"
    assert (outcome.unit, outcome.evidence) == (UNIT, EVIDENCE)


@pytest.mark.parametrize("yes", [0.79, 0.5, 0.3])
def test_judged_binary_inside_its_band_is_an_abstention(yes: float) -> None:
    """Given the judge's yes just below the threshold, in the middle, or at
    the band's lower edge, When it is judged, Then it is an abstention
    carrying the probability it read -- never a finding, never a pass."""
    outcome = _binary(KIND, yes)

    assert isinstance(outcome, Abstention), outcome
    assert outcome.confidence == pytest.approx(yes)
    assert outcome.question == KIND.id
    assert outcome.check == catalog_check("Kind")


@pytest.mark.parametrize("yes", [0.29, 0.0])
def test_judged_binary_below_its_band_is_a_pass(yes: float) -> None:
    """Given the judge's yes below the band, When it is judged, Then it is a
    pass whose confidence is the probability of the passing answer."""
    outcome = _binary(KIND, yes)

    assert isinstance(outcome, Pass), outcome
    assert outcome.confidence == pytest.approx(1 - yes)


def test_judged_binary_whose_no_is_the_finding_reads_the_no() -> None:
    """Given `implemented`, whose no is the finding, and a judge 90% sure the
    unit is not implemented, When it is judged, Then it is a finding with
    confidence 0.9; 90% sure it is implemented is a pass."""
    unfinished = _binary(IMPLEMENTED, 0.1)
    finished = _binary(IMPLEMENTED, 0.9)

    assert isinstance(unfinished, Finding), unfinished
    assert unfinished.confidence == pytest.approx(0.9)
    assert isinstance(finished, Pass), finished


# --- choice: the most likely option, `none` a pass -----------------------------


def test_judged_choice_naming_a_library_at_its_threshold_names_it() -> None:
    """Given a choice whose most likely option is a library at the
    threshold, When it is judged, Then the finding names that library and
    carries its probability."""
    outcome = judged(
        _ask(LIBRARIES, "Hand-rolled"),
        KEY,
        _decide({"lib_1": 0.7, "lib_2": 0.1, NONE: 0.2}),
        POLICY,
    )

    assert isinstance(outcome, Finding), outcome
    assert "markdown-it-py" in outcome.subject
    assert outcome.confidence == pytest.approx(0.7)


def test_judged_choice_below_its_threshold_abstains_whatever_is_top() -> None:
    """Given a choice whose most likely option, a library or none, is just
    below the threshold, When it is judged, Then it is an abstention."""
    library = judged(
        _ask(LIBRARIES, "Hand-rolled"),
        KEY,
        _decide({"lib_1": 0.69, "lib_2": 0.11, NONE: 0.2}),
        POLICY,
    )
    nothing = judged(
        _ask(LIBRARIES, "Hand-rolled"),
        KEY,
        _decide({"lib_1": 0.2, "lib_2": 0.11, NONE: 0.69}),
        POLICY,
    )

    assert isinstance(library, Abstention), library
    assert isinstance(nothing, Abstention), nothing


def test_judged_choice_of_none_at_its_threshold_is_a_pass() -> None:
    """Given a choice whose most likely option is none, at the threshold,
    When it is judged, Then it is a pass carrying none's probability."""
    outcome = judged(
        _ask(LIBRARIES, "Hand-rolled"),
        KEY,
        _decide({"lib_1": 0.2, "lib_2": 0.1, NONE: 0.7}),
        POLICY,
    )

    assert isinstance(outcome, Pass), outcome
    assert outcome.confidence == pytest.approx(0.7)


# --- score: the mass in the failing band, never the expectation alone --------


def test_judged_score_reads_the_mass_in_the_failing_band() -> None:
    """Given a three-level rubric whose expected level (0.8) sits near the
    middle while 60% of the mass is on `not asserted`, When it is judged,
    Then it is a finding with confidence 0.6: the band's mass is thresholded,
    not where the expectation lands."""
    outcome = judged(
        _ask(THEN_ASSERTED, "Then asserted"),
        KEY,
        _decide({"not asserted": 0.6, "partly": 0.0, "fully": 0.4}),
        POLICY,
    )

    assert isinstance(outcome, Finding), outcome
    assert outcome.confidence == pytest.approx(0.6)


@pytest.mark.parametrize(
    ("failing", "expected"),
    [(0.59, Abstention), (0.2, Abstention), (0.19, Pass)],
)
def test_judged_score_below_its_threshold_abstains_or_passes(
    failing: float, expected: type
) -> None:
    """Given the failing band's mass just below the threshold, at the band's
    lower edge, and below it, When it is judged, Then it abstains, abstains,
    and passes."""
    outcome = judged(
        _ask(THEN_ASSERTED, "Then asserted"),
        KEY,
        _decide({"not asserted": failing, "partly": 1 - failing, "fully": 0.0}),
        POLICY,
    )

    assert isinstance(outcome, expected), outcome


# --- what never meets a threshold ------------------------------------------------


def test_judged_uncalibrated_answer_never_meets_a_threshold() -> None:
    """Given a label-only answer the judge marks uncalibrated, carrying a
    sentinel 1.0, When it is judged, Then it is coverage naming the
    question, never a finding: a guess is not turned into certainty."""
    decision = Decision({KEY: {"yes": 1.0, "no": 0.0}}, uncalibrated=frozenset({KEY}))

    outcome = judged(_ask(KIND), KEY, decision, POLICY)

    assert isinstance(outcome, Coverage), outcome
    assert outcome.check == "Kind" and outcome.path == UNIT.path
    assert "kind" in outcome.reason


def test_judged_question_with_no_threshold_or_no_answer_is_coverage() -> None:
    """Given a question the policy holds no entry for, and an answer that
    omits the question or one of its options, When each is judged, Then
    each is coverage: an unanswered question is never a pass."""
    unpolicied = judged(_ask(KIND), KEY, _decide({"yes": 0.9}), ThresholdPolicy())
    missing = judged(_ask(KIND), KEY, Decision({}), POLICY)
    partial = judged(_ask(KIND), KEY, _decide({"yes": 0.9}), POLICY)

    assert isinstance(unpolicied, Coverage), unpolicied
    assert isinstance(missing, Coverage), missing
    assert isinstance(partial, Coverage), partial


def test_unanswered_question_names_its_unit_apart_from_its_reason() -> None:
    """Given the same unanswered question about two units, When each is
    judged, Then each coverage names its unit in the subject, and the
    reason, which says only why, is the same for both."""
    other = Ask(
        check=catalog_check("Kind"),
        question=KIND,
        unit=Unit(
            "src/app/domain/tax.py", UnitKind.FUNCTION, "tax", 1, 4, Layer.DOMAIN
        ),
        layer=Layer.DOMAIN,
        subject="tax: the subject",
        evidence=Evidence("src/app/domain/tax.py", 1, "tax"),
        text="def tax(): ...",
        context="",
    )
    first = judged(_ask(KIND), KEY, Decision({}), POLICY)
    second = judged(other, KEY, Decision({}), POLICY)

    assert isinstance(first, Coverage) and isinstance(second, Coverage)
    assert (first.subject, second.subject) == ("price: the subject", "tax: the subject")
    assert first.reason == second.reason
    assert "price" not in first.reason


def test_threshold_policy_refuses_an_empty_band_or_a_mismatched_form() -> None:
    """Given an entry whose pass bound is not below its finding bound, and a
    choice-form entry for a binary question, When the policy is built, Then
    each is refused: every judged check has a non-empty abstention band, and
    each entry's form follows its question's kind."""
    with pytest.raises(ValueError, match="band"):
        BandThreshold(finding_at=0.5, pass_below=0.5)
    with pytest.raises(ValueError, match="kind"):
        ThresholdPolicy({KIND.id: ChoiceThreshold(at=0.7)})


@given(st.floats(0.0, 1.0))
def test_judged_binary_outcome_always_carries_a_confidence_in_range(
    yes: float,
) -> None:
    """Given any probability of yes, When a binary question is judged, Then
    the finding, pass or abstention carries a confidence between 0 and 1."""
    outcome = _binary(KIND, yes)

    assert isinstance(outcome, Finding | Pass | Abstention), outcome
    assert outcome.confidence is not None
    assert 0.0 <= outcome.confidence <= 1.0
