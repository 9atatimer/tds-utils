"""ComplexityPort's contract, written once and run against every adapter.

Language-neutral promises: nothing from nothing, every function of the
sources named by its repository path, symbol and first line with its
cyclomatic complexity, and TimedOut rather than overrun a passed
deadline. A subclass supplies `port`.
"""

from __future__ import annotations

from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.model import Complexity, Metrics
from adherence.ports.complexity import ComplexityPort

RULES = "src/pkg/rules.py"
SOURCES = {
    RULES: (
        b"def simple():\n"
        b"    return 1\n"
        b"\n"
        b"\n"
        b"def branchy(x):\n"
        b"    if x:\n"
        b"        return 1\n"
        b"    elif x > 2:\n"
        b"        return 2\n"
        b"    return 3\n"
    ),
}
# What the sources' functions measure: one path through `simple`, three
# through `branchy`.
MEASURED = (
    Complexity(RULES, "simple", 1, 1),
    Complexity(RULES, "branchy", 5, 3),
)


class ComplexityContract:
    def port(self) -> ComplexityPort:
        raise NotImplementedError("a contract subclass supplies its adapter")

    def test_measure_of_nothing_is_empty(self) -> None:
        """Given no sources, When complexity is measured, Then no function is
        named."""
        answer = self.port().measure({}, None)

        assert isinstance(answer, Metrics), answer
        assert answer.complexity == ()

    def test_measure_names_each_function_with_its_complexity(self) -> None:
        """Given sources with a straight and a branching function, When
        complexity is measured, Then each is named by path, symbol and first
        line with its cyclomatic complexity."""
        answer = self.port().measure(SOURCES, None)

        assert isinstance(answer, Metrics), answer
        assert set(answer.complexity) == set(MEASURED)

    def test_measure_past_the_deadline_times_out(self) -> None:
        """Given a deadline already passed, When complexity is measured, Then
        the answer is TimedOut, not a partial measurement."""
        answer = self.port().measure(SOURCES, Deadline(epoch_seconds=0.0))

        assert isinstance(answer, TimedOut)
