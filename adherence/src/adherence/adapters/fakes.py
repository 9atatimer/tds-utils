"""adapters/fakes.py -- an in-memory adapter per port, for tests only.

container.py never imports this module; a test passes these in. Each
deadline-bound fake is scriptable to answer TimedOut.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import Declaration, layer_of
from adherence.domain.model import (
    Clone,
    CodeModel,
    Complexity,
    Metrics,
    Unit,
    UnitKind,
)
from adherence.domain.parameters import Vocabulary
from adherence.domain.questions import Decision, Schema, State, Unavailable
from adherence.domain.records import DesignRecords, RecordsUnavailable
from adherence.domain.target import Base, Head
from adherence.ports.repository import Absent, Refused


class FakeRepository:
    """RepositoryPort over a mapping of target -> path -> answer: the bytes,
    or the Refused or TimedOut the test scripts for that path."""

    def __init__(
        self, files: Mapping[Base | Head, Mapping[str, bytes | Refused | TimedOut]]
    ) -> None:
        self._files = files

    def read(
        self, path: str, at: Base | Head, deadline: Deadline | None
    ) -> bytes | Absent | Refused | TimedOut:
        found = self._files.get(at, {}).get(path)
        return Absent(path) if found is None else found

    def tree(
        self, at: Base | Head, deadline: Deadline | None
    ) -> tuple[str, ...] | TimedOut:
        return tuple(sorted(self._files.get(at, {})))


class FakeCodeModel:
    """CodeModelPort over facts the test configures: a file unit per source
    (but a source the facts hold Unparsed), plus the facts of those sources,
    each unit re-layered by the declaration. Its clock is frozen at `now`,
    so a deadline at or before it has passed."""

    def __init__(self, facts: CodeModel | None = None, *, now: float = 1e9) -> None:
        self._facts = facts if facts is not None else CodeModel()
        self._now = now

    def model(
        self,
        sources: Mapping[str, bytes],
        declaration: Declaration,
        vocabulary: Vocabulary,
        deadline: Deadline | None,
    ) -> CodeModel | TimedOut:
        if deadline is not None and deadline.epoch_seconds <= self._now:
            return TimedOut("model the sources")
        f = self._facts
        unparsed = {u.path for u in f.unparsed}
        files = tuple(
            Unit(path, UnitKind.FILE, None, 1, 1, layer_of(path, None, declaration))
            for path in sorted(sources)
            if path not in unparsed
        )
        return CodeModel(
            units=files
            + tuple(
                _relayered(u, declaration)
                for u in f.units
                if u.path in sources and u.kind is not UnitKind.FILE
            ),
            imports=tuple(e for e in f.imports if e.path in sources),
            definitions=tuple(
                replace(d, unit=_relayered(d.unit, declaration))
                for d in f.definitions
                if d.unit.path in sources
            ),
            references=tuple(r for r in f.references if r.path in sources),
            calls=tuple(c for c in f.calls if c.path in sources),
            accesses=tuple(a for a in f.accesses if a.path in sources),
            writes=tuple(w for w in f.writes if w.path in sources),
            conditionals=tuple(c for c in f.conditionals if c.path in sources),
            members=tuple(m for m in f.members if m.path in sources),
            test_cases=tuple(t for t in f.test_cases if t.path in sources),
            regions=tuple(r for r in f.regions if r.path in sources),
            unparsed=tuple(u for u in f.unparsed if u.path in sources),
        )


def _relayered(unit: Unit, declaration: Declaration) -> Unit:
    return replace(unit, layer=layer_of(unit.path, unit.start, declaration))


class FakeComplexity:
    """ComplexityPort answering the fixed complexity the test configures, or
    the TimedOut it scripts."""

    def __init__(self, answer: tuple[Complexity, ...] | TimedOut = ()) -> None:
        self._answer = answer

    def measure(
        self, sources: Mapping[str, bytes], deadline: Deadline | None
    ) -> Metrics | TimedOut:
        if isinstance(self._answer, TimedOut):
            return self._answer
        return Metrics(complexity=self._answer)


class FakeDuplication:
    """DuplicationPort answering the fixed clones the test configures, or the
    TimedOut it scripts."""

    def __init__(self, answer: tuple[Clone, ...] | TimedOut = ()) -> None:
        self._answer = answer

    def measure(
        self, sources: Mapping[str, bytes], deadline: Deadline | None
    ) -> Metrics | TimedOut:
        if isinstance(self._answer, TimedOut):
            return self._answer
        return Metrics(clones=self._answer)


class FakeRecords:
    """RecordsPort over a mapping of target -> the records, the
    RecordsUnavailable or the TimedOut the test scripts for it, so base and
    head can hold different records. A target it does not hold has none."""

    def __init__(
        self,
        by_target: Mapping[Base | Head, DesignRecords | RecordsUnavailable | TimedOut],
    ) -> None:
        self._by_target = by_target

    def records(
        self, at: Base | Head, declaration: Declaration, deadline: Deadline | None
    ) -> DesignRecords | RecordsUnavailable | TimedOut:
        return self._by_target.get(
            at, RecordsUnavailable("no design record at this target")
        )


class FakeDecision:
    """DecisionPort that gives every schema the one answer the test scripts:
    a Decision, Unavailable, or TimedOut. It keeps every state it was asked
    about, in order."""

    def __init__(self, answer: Decision | Unavailable | TimedOut) -> None:
        self._answer = answer
        self.asked: list[tuple[State, Schema]] = []

    def decide(
        self, state: State, schema: Schema, deadline: Deadline | None
    ) -> Decision | Unavailable | TimedOut:
        self.asked.append((state, schema))
        return self._answer
