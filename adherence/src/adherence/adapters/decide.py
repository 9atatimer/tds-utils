"""adapters/decide.py -- DecisionPort over the fleet's decide client.

The judge is asked through `bin/decide run`, whose record format the
adapter speaks (docs/ops/decide.md): one record per call, the unit under
judgement as the record's `state`, every question of the Schema under its
key as the domain fixed it (ARCHITECTURE.ARCH-ADHERENCE.md, Module map and
Security mitigations). Nothing the repository supplies is ever put in a
question: the instructions, options and criteria are the domain's, and
the decide client can call no tool.
"""

from __future__ import annotations

from collections.abc import Mapping

from adherence.domain.questions import Question, QuestionKind, Schema, State

# --- Constants ---------------------------------------------------------------

# decide's names for the domain's kinds of question.
DECIDE_TYPES: Mapping[QuestionKind, str] = {
    QuestionKind.BINARY: "noul",
    QuestionKind.CHOICE: "choice",
    QuestionKind.SCORE: "score",
}
# The record's id is the caller's own, copied to the answer and never sent
# to the model.
RECORD_ID = "adherence"

# --- Pure helpers ------------------------------------------------------------


def _decide_question(question: Question) -> dict[str, object]:
    """One question as decide reads it: a binary question is a yes/no
    (noul) with no criteria; a choice names one criterion per option; a
    score lists its levels' criteria lowest first."""
    asked: dict[str, object] = {
        "type": DECIDE_TYPES[question.kind],
        "instructions": question.instructions,
    }
    if question.kind is QuestionKind.CHOICE:
        asked["criteria"] = dict(zip(question.options, question.criteria, strict=True))
    elif question.kind is QuestionKind.SCORE:
        asked["criteria"] = list(question.criteria)
    return asked


def decide_record(state: State, schema: Schema) -> dict[str, object]:
    """The decide record for one call: the unit -- where it is, its layer,
    its text and each question's data -- as the state, which decide sends
    as data, and the schema's questions under their keys."""
    unit = state.unit
    return {
        "id": RECORD_ID,
        "state": {
            "unit": {
                "path": unit.path,
                "symbol": unit.symbol,
                "kind": unit.kind.value,
                "layer": unit.layer.value if unit.layer is not None else None,
            },
            "text": state.text,
            "context": dict(state.context),
        },
        "questions": {
            key: _decide_question(question)
            for key, question in schema.questions.items()
        },
    }
