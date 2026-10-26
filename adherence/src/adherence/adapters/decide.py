"""adapters/decide.py -- DecisionPort over the fleet's decide client.

The judge is asked through `bin/decide run`, whose record format the
adapter speaks (docs/ops/decide.md): one record per call, the unit under
judgement as the record's `state`, every question of the Schema under its
key as the domain fixed it (ARCHITECTURE.ARCH-ADHERENCE.md, Module map and
Security mitigations). Nothing the repository supplies is ever put in a
question: the instructions, options and criteria are the domain's, and
the decide client can call no tool.

The client is spawned through `analyzer_process` in a scratch directory
outside the repository, the record on its standard input, with the
allowlisted environment plus its own configuration -- the DECIDE_*
variables the composition root names (the door's address on the laptop,
the hosted gateway and its token in CI) -- and the time left before the
Deadline as its timeout. A schema past decide's per-record limit is split
across records. decide's failure classes become the port's typed
failures: `rejected` is Rejected, every other is Unavailable.
"""

from __future__ import annotations

import json
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from adherence.adapters.analyzer_process import NotRan, remaining, run_analyzer
from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.questions import (
    NO,
    YES,
    Decision,
    Question,
    QuestionKind,
    Rejected,
    Schema,
    State,
    Unavailable,
)

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
OPERATION = "ask the judge through decide"
# decide validates at most this many questions per record (docs/ops/decide.md).
MAX_QUESTIONS = 64
# The client's own configuration is the only thing beside the allowlist.
OWN_PREFIX = "DECIDE_"
REJECTED = "rejected"

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


def _chunks(schema: Schema) -> list[Schema]:
    """The schema in records decide accepts, at most MAX_QUESTIONS each; an
    empty schema is one empty record, for decide to reject."""
    keys = list(schema.questions)
    if not keys:
        return [schema]
    return [
        Schema({k: schema.questions[k] for k in keys[i : i + MAX_QUESTIONS]})
        for i in range(0, len(keys), MAX_QUESTIONS)
    ]


def _probabilities(
    question: Question, answer: Mapping[str, object]
) -> tuple[dict[str, float], bool] | None:
    """One normalized decide answer as a probability per option, and whether
    it is calibrated; None when it cannot be read against the question."""
    calibrated = answer.get("calibrated") is True
    if question.kind is QuestionKind.BINARY:
        p_true = answer.get("p_true")
        if not isinstance(p_true, int | float):
            return {YES: 0.0, NO: 0.0}, False
        return {YES: float(p_true), NO: 1.0 - float(p_true)}, calibrated
    received = answer.get("probabilities")
    if question.kind is QuestionKind.CHOICE:
        if not isinstance(received, dict):
            return {o: 0.0 for o in question.options}, False
        return {o: float(received.get(o, 0.0)) for o in question.options}, calibrated
    if not isinstance(received, list) or len(received) != len(question.options):
        return ({o: 0.0 for o in question.options}, False) if received is None else None
    return dict(zip(question.options, map(float, received), strict=True)), calibrated


def parse_answer(
    stdout: str, returncode: int, schema: Schema
) -> Decision | Unavailable | Rejected:
    """decide's printed answer to one record as the port's value: a Decision
    with each question's probabilities (a label-only answer uncalibrated),
    or its failure class as Rejected or Unavailable."""
    try:
        printed = json.loads(stdout)
    except json.JSONDecodeError:
        return Unavailable(f"decide exited {returncode} printing no answer")
    if not isinstance(printed, dict):
        return Unavailable(f"decide exited {returncode} printing no answer")
    if printed.get("ok") is not True:
        error = printed.get("error")
        failure = error if isinstance(error, dict) else {}
        kind, message = failure.get("class"), failure.get("message", "no message")
        if kind == REJECTED:
            return Rejected(f"decide rejected the record: {message}")
        return Unavailable(f"decide {kind}: {message}")
    answers = printed.get("answers")
    if not isinstance(answers, dict):
        return Unavailable("decide answered with no answers")
    probabilities: dict[str, dict[str, float]] = {}
    uncalibrated: set[str] = set()
    for key, question in schema.questions.items():
        answer = answers.get(key)
        read = _probabilities(question, answer) if isinstance(answer, dict) else None
        if read is None:
            continue
        probabilities[key], calibrated = read
        if not calibrated:
            uncalibrated.add(key)
    return Decision(probabilities, frozenset(uncalibrated))


# --- Adapter -----------------------------------------------------------------


class DecideDecision:
    """DecisionPort over the decide client, run once per record."""

    def __init__(
        self,
        *,
        command: Sequence[str],
        configuration: Mapping[str, str],
        clock: Callable[[], float] = time.time,
    ) -> None:
        foreign = sorted(k for k in configuration if not k.startswith(OWN_PREFIX))
        if foreign:
            raise ValueError(
                f"not the decide client's own configuration: {', '.join(foreign)}"
            )
        self._command = tuple(command)
        self._configuration = dict(configuration)
        self._clock = clock

    @property
    def configuration(self) -> dict[str, str]:
        """The client's own configuration, as the composition root gave it."""
        return dict(self._configuration)

    def _ask(
        self, state: State, schema: Schema, deadline: Deadline | None
    ) -> Decision | Unavailable | Rejected | TimedOut:
        left = remaining(deadline, self._clock())
        configuration = dict(self._configuration)
        if left is not None:
            configuration["DECIDE_TIMEOUT_MS"] = str(max(1, int(left * 1000)))
        with tempfile.TemporaryDirectory(prefix="adherence-decide-") as scratch:
            root = Path(scratch)
            ran = run_analyzer(
                self._command,
                cwd=root,
                scratch=root,
                timeout=left,
                stdin=json.dumps(decide_record(state, schema)),
                configuration=configuration,
            )
        if isinstance(ran, NotRan):
            if ran.timed_out:
                return TimedOut(OPERATION)
            return Unavailable(f"decide {ran.reason}")
        return parse_answer(ran.stdout, ran.returncode, schema)

    def decide(
        self, state: State, schema: Schema, deadline: Deadline | None
    ) -> Decision | Unavailable | Rejected | TimedOut:
        left = remaining(deadline, self._clock())
        if left is not None and left <= 0:
            return TimedOut(OPERATION)
        probabilities: dict[str, Mapping[str, float]] = {}
        uncalibrated: set[str] = set()
        for chunk in _chunks(schema):
            answer = self._ask(state, chunk, deadline)
            if not isinstance(answer, Decision):
                return answer
            probabilities.update(answer.probabilities)
            uncalibrated.update(answer.uncalibrated)
        return Decision(probabilities, frozenset(uncalibrated))
