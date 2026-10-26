"""application/latch.py -- no port call after the first TimedOut.

The bound is a deadline, not a clock (ARCHITECTURE.ARCH-ADHERENCE.md, Key
Decisions): only adapters compare the Deadline to the time, and once any
deadline-bound port has answered TimedOut the run asks no port anything
more. Each use case wraps the ports it is given in these, sharing one
Latch; a call after the first TimedOut is answered TimedOut naming it,
without reaching the port, and the use case records it as coverage like
any other. The application reads no time.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypeVar

from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import (
    Declaration,
    Landing,
    NoLandingPR,
    ReviewsUnavailable,
    Unknown,
)
from adherence.domain.model import CodeLanguage, CodeModel, Metrics, MetricsUnavailable
from adherence.domain.parameters import Vocabulary
from adherence.domain.questions import Decision, Schema, State, Unavailable
from adherence.domain.records import DesignRecords, Radar, RecordsUnavailable
from adherence.domain.report import Recorded, Report
from adherence.domain.target import Base, ChangedPaths, Head
from adherence.ports.code_model import CodeModelPort
from adherence.ports.complexity import ComplexityPort
from adherence.ports.decision import DecisionPort
from adherence.ports.duplication import DuplicationPort
from adherence.ports.records import RecordsPort
from adherence.ports.report_store import ReportStore, StoreMiss
from adherence.ports.repository import Absent, Refused, RepositoryPort
from adherence.ports.review import ReviewPort

Answer = TypeVar("Answer")

# --- The latch ---------------------------------------------------------------


@dataclass(slots=True)
class Latch:
    """The first TimedOut any of a run's ports answered, once one has."""

    first: TimedOut | None = None

    @property
    def tripped(self) -> bool:
        return self.first is not None

    def seen(self, answer: Answer) -> Answer:
        """A port's answer, passed through; the first TimedOut is kept."""
        if isinstance(answer, TimedOut) and self.first is None:
            self.first = answer
        return answer

    def unasked(self, operation: str) -> TimedOut:
        """The answer to a call the run no longer makes."""
        first = self.first.operation if self.first is not None else "the run"
        return TimedOut(f"{operation} (not asked: {first} timed out first)")


# --- The latched ports -------------------------------------------------------


class LatchedRepository:
    """RepositoryPort that asks nothing once the latch has tripped."""

    def __init__(self, inner: RepositoryPort, latch: Latch) -> None:
        self._inner = inner
        self._latch = latch

    def read(
        self, path: str, at: Base | Head, deadline: Deadline | None
    ) -> bytes | Absent | Refused | TimedOut:
        if self._latch.tripped:
            return self._latch.unasked(f"read {path}")
        return self._latch.seen(self._inner.read(path, at, deadline))

    def tree(
        self, at: Base | Head, deadline: Deadline | None
    ) -> tuple[str, ...] | Refused | TimedOut:
        if self._latch.tripped:
            return self._latch.unasked("list the tree")
        return self._latch.seen(self._inner.tree(at, deadline))

    def changed(
        self, base: Base, head: Head, deadline: Deadline | None
    ) -> ChangedPaths | Refused | TimedOut:
        if self._latch.tripped:
            return self._latch.unasked("tell what the change did")
        return self._latch.seen(self._inner.changed(base, head, deadline))

    def history(
        self, path: str, base: Base, deadline: Deadline | None
    ) -> tuple[str, ...] | Refused | TimedOut:
        if self._latch.tripped:
            return self._latch.unasked(f"list the history of {path}")
        return self._latch.seen(self._inner.history(path, base, deadline))


class LatchedReviews:
    """ReviewPort that asks nothing once the latch has tripped."""

    def __init__(self, inner: ReviewPort, latch: Latch) -> None:
        self._inner = inner
        self._latch = latch

    def approvals(
        self, commit: str, deadline: Deadline | None
    ) -> Landing | NoLandingPR | Unknown | ReviewsUnavailable | TimedOut:
        if self._latch.tripped:
            return self._latch.unasked("read the reviews")
        return self._latch.seen(self._inner.approvals(commit, deadline))


class LatchedCodeModel:
    """CodeModelPort that asks nothing once the latch has tripped."""

    def __init__(self, inner: CodeModelPort, latch: Latch) -> None:
        self._inner = inner
        self._latch = latch

    def model(
        self,
        sources: Mapping[str, bytes],
        declaration: Declaration,
        vocabulary: Vocabulary,
        deadline: Deadline | None,
    ) -> CodeModel | TimedOut:
        if self._latch.tripped:
            return self._latch.unasked("model the sources")
        return self._latch.seen(
            self._inner.model(sources, declaration, vocabulary, deadline)
        )


class LatchedComplexity:
    """ComplexityPort that asks nothing once the latch has tripped."""

    def __init__(self, inner: ComplexityPort, latch: Latch) -> None:
        self._inner = inner
        self._latch = latch

    def measure(
        self, sources: Mapping[str, bytes], deadline: Deadline | None
    ) -> Metrics | MetricsUnavailable | TimedOut:
        if self._latch.tripped:
            return self._latch.unasked("measure complexity")
        return self._latch.seen(self._inner.measure(sources, deadline))


class LatchedDuplication:
    """DuplicationPort that asks nothing once the latch has tripped."""

    def __init__(self, inner: DuplicationPort, latch: Latch) -> None:
        self._inner = inner
        self._latch = latch

    def measure(
        self, sources: Mapping[str, bytes], deadline: Deadline | None
    ) -> Metrics | MetricsUnavailable | TimedOut:
        if self._latch.tripped:
            return self._latch.unasked("find clones")
        return self._latch.seen(self._inner.measure(sources, deadline))


class LatchedRecords:
    """RecordsPort that asks nothing once the latch has tripped."""

    def __init__(self, inner: RecordsPort, latch: Latch) -> None:
        self._inner = inner
        self._latch = latch

    def records(
        self, at: Base | Head, declaration: Declaration, deadline: Deadline | None
    ) -> DesignRecords | RecordsUnavailable | TimedOut:
        if self._latch.tripped:
            return self._latch.unasked("read the design records")
        return self._latch.seen(self._inner.records(at, declaration, deadline))

    def radar(
        self, at: Base | Head, declaration: Declaration, deadline: Deadline | None
    ) -> Radar | RecordsUnavailable | TimedOut:
        if self._latch.tripped:
            return self._latch.unasked("read the radar")
        return self._latch.seen(self._inner.radar(at, declaration, deadline))


class LatchedDecision:
    """DecisionPort that asks nothing once the latch has tripped."""

    def __init__(self, inner: DecisionPort, latch: Latch) -> None:
        self._inner = inner
        self._latch = latch

    def decide(
        self, state: State, schema: Schema, deadline: Deadline | None
    ) -> Decision | Unavailable | TimedOut:
        if self._latch.tripped:
            return self._latch.unasked("ask the judge")
        return self._latch.seen(self._inner.decide(state, schema, deadline))


class LatchedReports:
    """ReportStore whose `get` asks nothing once the latch has tripped;
    `put` runs after the verdict and is never latched."""

    def __init__(self, inner: ReportStore, latch: Latch) -> None:
        self._inner = inner
        self._latch = latch

    def get(
        self, repository: str, revision: str, identity: str, deadline: Deadline | None
    ) -> Report | StoreMiss | TimedOut:
        if self._latch.tripped:
            return self._latch.unasked("read a kept report")
        return self._latch.seen(
            self._inner.get(repository, revision, identity, deadline)
        )

    def put(self, report: Report) -> Recorded:
        return self._inner.put(report)


def latched_analyzers(
    analyzers: Mapping[CodeLanguage, CodeModelPort], latch: Latch
) -> dict[CodeLanguage, CodeModelPort]:
    """Each language's analyzer behind the latch."""
    return {
        language: LatchedCodeModel(analyzer, latch)
        for language, analyzer in analyzers.items()
    }
