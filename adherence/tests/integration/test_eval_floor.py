"""The labelled set against the real judge, under the shipped thresholds:
the floor that goes in CI (the decision-models skill, Evaluation before
adoption; the gates skill's law: a change is judged against the floor as
it stood before it). Marked integration and skipped unless a judge is
configured, since it spends against the judge's budget.

The floor, while the set is a handful per id: no example is answered
confidently wrong -- no finding on an example labelled a pass, no pass on
one labelled a finding, no finding naming another library. Abstentions
are allowed and reported. Each question and each class is reported apart,
never as one blended number.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from adherence.adapters.decide import DecideDecision
from adherence.container import SHIPPED_PARAMETERS
from adherence.domain.finding import Finding
from adherence.domain.questions import (
    QUESTION_KINDS,
    Abstention,
    Decision,
    Pass,
    QuestionKind,
    judged,
    schemas,
)
from tests.evals_kit import Example, examples

DECIDE = Path(__file__).resolve().parents[3] / "bin" / "decide"
COMMAND = (str(DECIDE), "run", "--model", "clef", "--tool", "adherence")
HOSTED = ("DECIDE_GATEWAY_URL", "DECIDE_GATEWAY_TOKEN")
CONFIGURED = all(os.environ.get(k) for k in HOSTED) or bool(
    os.environ.get("DECIDE_URL")
)


def _judge() -> DecideDecision:
    if all(os.environ.get(k) for k in HOSTED):
        configuration = {"DECIDE_BACKEND": "cf-ai-gateway"}
        configuration.update({k: os.environ[k] for k in HOSTED})
    else:
        configuration = {
            "DECIDE_BACKEND": "systemone",
            "DECIDE_URL": os.environ["DECIDE_URL"],
        }
    return DecideDecision(command=COMMAND, configuration=configuration)


def _wrong(example: Example, outcome: object) -> bool:
    """Whether the judge answered the example confidently wrong."""
    if isinstance(outcome, Finding):
        if not example.is_finding:
            return True
        named = example.question.kind is QuestionKind.CHOICE
        return named and not outcome.subject.endswith(f" {example.label}")
    if isinstance(outcome, Pass):
        return example.is_finding
    return False


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("node") is None, reason="node runs bin/decide")
@pytest.mark.skipif(not CONFIGURED, reason="no judge configured (DECIDE_* unset)")
@pytest.mark.parametrize("question_id", sorted(QUESTION_KINDS))
def test_labelled_set_is_never_answered_confidently_wrong(question_id: str) -> None:
    """Given one question id's labelled examples and the shipped thresholds,
    When the real judge answers each as a judged check would ask it, Then
    no example is answered confidently wrong; the report per class names
    every wrong answer and counts the abstentions."""
    judge = _judge()
    policy = SHIPPED_PARAMETERS.thresholds
    wrong: list[str] = []
    abstained = {True: 0, False: 0}
    for example in examples(question_id):
        ask = example.ask()
        (asking,) = schemas([ask])
        (key,) = asking.asks
        answer = judge.decide(asking.state, asking.schema, None)
        assert isinstance(answer, Decision), (example.id, answer)
        outcome = judged(ask, key, answer, policy)
        if isinstance(outcome, Abstention):
            abstained[example.is_finding] += 1
        if _wrong(example, outcome):
            wrong.append(f"{example.id} (labelled {example.label}): {outcome}")
    report = (
        f"{question_id}: abstained on {abstained[True]} labelled a finding and "
        f"{abstained[False]} labelled a pass"
    )
    assert not wrong, f"{report}; confidently wrong:\n" + "\n".join(wrong)
