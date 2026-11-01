"""domain/questions.py -- what a judged check asks, and what the judge answers.

A judged check puts one bounded question about one unit to the judge as a
Schema over the unit's State and receives a probability per allowed answer
(ARCHITECTURE.ARCH-ADHERENCE.md, Facts and judgements told apart). The
judge's failure is typed: Unavailable is a value, never an exception.
ThresholdPolicy turns a Decision into a finding, a pass or an abstention,
one entry per question id; no judged check runs yet, so it holds none.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from adherence.domain.model import Unit

# --- Values ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Question:
    """One bounded question: its stable id and its allowed answers."""

    id: str
    options: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Schema:
    """Every question about one unit, put to the judge together."""

    questions: tuple[Question, ...]


@dataclass(frozen=True, slots=True)
class State:
    """The unit a schema is about, and its text: data to be judged."""

    unit: Unit
    text: str


@dataclass(frozen=True, slots=True)
class Decision:
    """The judge's answer: per question id, a probability per option."""

    probabilities: Mapping[str, Mapping[str, float]]


@dataclass(frozen=True, slots=True)
class Unavailable:
    """The judge could not be asked, with the reason."""

    reason: str


@dataclass(frozen=True, slots=True)
class ThresholdPolicy:
    """Per judged question id, the threshold and the abstention band. Empty:
    no judged check runs in this suite version."""
