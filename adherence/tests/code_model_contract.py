"""CodeModelPort's contract, written once and run against every adapter.

Language-neutral promises: a file unit for every source, each unit in the
layer the declaration gives it, nothing from nothing, and TimedOut rather
than overrun a passed deadline. A subclass supplies `port`.
"""

from __future__ import annotations

from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import Declaration, parse_declaration
from adherence.domain.model import CodeModel, Layer, UnitKind
from adherence.domain.parameters import Vocabulary
from adherence.ports.code_model import CodeModelPort

VOCABULARY = Vocabulary(regions={"predicates": Layer.DOMAIN})
SOURCES = {
    "src/pkg/__init__.py": b"",
    "src/pkg/rules.py": b"def rule(x: int) -> int:\n    return x\n",
    "scratch.py": b"y = 2\n",
}
DECLARATION = b'[layers]\ndomain = ["src/pkg/**"]\n'


def declaration() -> Declaration:
    parsed = parse_declaration(DECLARATION)
    assert isinstance(parsed, Declaration)
    return parsed


class CodeModelContract:
    def port(self) -> CodeModelPort:
        raise NotImplementedError("a contract subclass supplies its adapter")

    def _model(self) -> CodeModel:
        model = self.port().model(SOURCES, declaration(), VOCABULARY, None)
        assert isinstance(model, CodeModel), model
        return model

    def test_model_has_a_file_unit_per_source_in_its_layer(self) -> None:
        """Given sources and a declaration covering some of them, When they are
        modelled, Then each source is one file unit, in its declared layer or
        none when uncovered."""
        files = {u.path: u.layer for u in self._model().units if u.kind is UnitKind.FILE}

        assert files == {
            "src/pkg/__init__.py": Layer.DOMAIN,
            "src/pkg/rules.py": Layer.DOMAIN,
            "scratch.py": None,
        }

    def test_model_of_nothing_is_empty(self) -> None:
        """Given no sources, When they are modelled, Then the model holds no unit."""
        model = self.port().model({}, declaration(), VOCABULARY, None)

        assert isinstance(model, CodeModel)
        assert model.units == ()

    def test_model_past_the_deadline_times_out(self) -> None:
        """Given a deadline already passed, When sources are modelled,
        Then the answer is TimedOut, not a partial model."""
        answer = self.port().model(
            SOURCES, declaration(), VOCABULARY, Deadline(epoch_seconds=0.0)
        )

        assert isinstance(answer, TimedOut)
