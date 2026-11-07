"""Read the labelled set under adherence/evals/ (its README.md documents
the format): one JSON object per line, one file per question id."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from adherence.domain.finding import Evidence
from adherence.domain.model import Unit, UnitKind
from adherence.domain.qualities import catalog_check
from adherence.domain.questions import (
    DOES_IO,
    HAND_ROLLED_ID,
    IMPLEMENTED,
    INVARIANT_BROKEN,
    KIND,
    NONE,
    RULES_ELSEWHERE,
    SAME_CONCEPT,
    SCATTERED_POLICY,
    THEN_ASSERTED,
    Ask,
    Question,
    QuestionKind,
    hand_rolled_question,
    libraries_context,
    library_keys,
)

EVALS = Path(__file__).resolve().parents[1] / "evals"
QUESTIONS: Mapping[str, Question] = {
    q.id: q
    for q in (
        KIND,
        DOES_IO,
        SAME_CONCEPT,
        SCATTERED_POLICY,
        INVARIANT_BROKEN,
        RULES_ELSEWHERE,
        THEN_ASSERTED,
        IMPLEMENTED,
    )
}
# The check that asks each question.
CHECKS: Mapping[str, str] = {
    KIND.id: "Kind",
    DOES_IO.id: "Purity",
    SAME_CONCEPT.id: "Language",
    SCATTERED_POLICY.id: "Decision",
    INVARIANT_BROKEN.id: "Boundary",
    RULES_ELSEWHERE.id: "Anemic",
    THEN_ASSERTED.id: "Then asserted",
    IMPLEMENTED.id: "Done",
    HAND_ROLLED_ID: "Hand-rolled",
}


@dataclass(frozen=True)
class Example:
    """One labelled state: the answer its question should get."""

    question_id: str
    id: str
    label: str
    text: str
    context: str
    note: str
    options: tuple[str, ...] = ()

    @property
    def question(self) -> Question:
        if self.question_id == HAND_ROLLED_ID:
            return hand_rolled_question(len(self.options))
        return QUESTIONS[self.question_id]

    @property
    def named(self) -> dict[str, str]:
        """A choice example's libraries under their option keys."""
        return library_keys(self.options)

    @property
    def answer(self) -> str:
        """The option the label is: a choice labels a library by name, which
        the question offers under its key."""
        keys = {name: key for key, name in self.named.items()}
        return keys.get(self.label, self.label)

    @property
    def is_finding(self) -> bool:
        """Whether the label is an answer that is a finding."""
        question = self.question
        if question.kind is QuestionKind.CHOICE:
            return self.label != NONE
        return self.label in question.failing

    def ask(self) -> Ask:
        """The example as a judged check would ask it."""
        unit = Unit(f"evals/{self.question_id}", UnitKind.FUNCTION, self.id, 1, 1, None)
        return Ask(
            check=catalog_check(CHECKS[self.question_id]),
            question=self.question,
            unit=unit,
            layer=None,
            subject=self.id,
            evidence=Evidence(unit.path, 1, self.id),
            text=self.text,
            context=libraries_context(self.named) if self.options else self.context,
            named=self.named,
        )


def examples(question_id: str) -> list[Example]:
    """The labelled examples of one question id, in file order."""
    path = EVALS / f"{question_id}.jsonl"
    found: list[Example] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        found.append(
            Example(
                question_id,
                record["id"],
                record["label"],
                record["text"],
                record.get("context", ""),
                record["note"],
                tuple(record.get("options", ())),
            )
        )
    return found
