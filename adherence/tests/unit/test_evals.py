"""The labelled set under adherence/evals/ and the shipped thresholds chosen
from it (ARCHITECTURE.ARCH-ADHERENCE.md, Facts and judgements told apart;
the decision-models skill, Evaluation before adoption).

The set is small -- six examples per question id, three that are a finding
and three that are not -- so it proves the plumbing and catches a
confidently wrong judge; it supports no rate. The shipped thresholds are
therefore provisional and conservative: a finding needs the judge at or
above 0.9 (0.85 for the score and the choice), and the abstention band is
wide. The floor -- no example of the set answered confidently wrong -- is
tests/integration/test_eval_floor.py, run against the real judge on
demand.
"""

from __future__ import annotations

from adherence.container import SHIPPED_PARAMETERS
from adherence.domain.questions import NONE, QUESTION_KINDS
from tests.evals_kit import EVALS, examples

# A handful per id: enough of each class that one class is never missing.
AT_LEAST = 2


def test_labelled_set_has_findings_and_passes_for_every_question() -> None:
    """Given the nine question ids, When the labelled set is read, Then each
    has its own file with at least two examples labelled a finding and two
    labelled a pass, every example id unique."""
    seen: set[str] = set()
    for question_id in QUESTION_KINDS:
        assert (EVALS / f"{question_id}.jsonl").is_file(), question_id
        labelled = examples(question_id)
        findings = [e for e in labelled if e.is_finding]
        passes = [e for e in labelled if not e.is_finding]
        assert len(findings) >= AT_LEAST, question_id
        assert len(passes) >= AT_LEAST, question_id
        ids = {e.id for e in labelled}
        assert len(ids) == len(labelled) and not ids & seen, question_id
        seen |= ids


def test_every_label_is_one_of_its_questions_options() -> None:
    """Given every labelled example, When it is read against its question,
    Then its label is one of the question's options, it has a text to judge
    and a note saying why it is labelled so, and a choice example lists its
    libraries without `none`, which the question adds."""
    for question_id in QUESTION_KINDS:
        for example in examples(question_id):
            assert example.label in example.question.options, example.id
            assert example.text.strip(), example.id
            assert example.note.strip(), example.id
            assert NONE not in example.options, example.id


def test_shipped_thresholds_hold_an_entry_per_question_in_its_kinds_form() -> None:
    """Given the parameters the composition root ships, When their threshold
    policy is read, Then it holds one entry for each of the nine question
    ids; the policy itself refuses an entry not in its question kind's
    form or with an empty abstention band."""
    assert set(SHIPPED_PARAMETERS.thresholds.entries) == set(QUESTION_KINDS)
