"""adapters/fakes.py -- an in-memory adapter per port, for tests only.

container.py never imports this module; a test passes these in. Each
deadline-bound fake is scriptable to answer TimedOut.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import replace

from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import (
    Declaration,
    Landing,
    NoLandingPR,
    ReviewsUnavailable,
    Unknown,
    layer_of,
)
from adherence.domain.model import (
    Clone,
    CodeModel,
    Complexity,
    Metrics,
    MetricsUnavailable,
    Unit,
    UnitKind,
    merged,
)
from adherence.domain.parameters import Vocabulary
from adherence.domain.questions import Decision, Schema, State, Unavailable
from adherence.domain.records import DesignRecords, Radar, RecordsUnavailable
from adherence.domain.target import Base, ChangedPaths, Head
from adherence.ports.repository import Absent, Refused

NO_REVIEWS = "the fake reviews know no landing of this commit"


class FakeRepository:
    """RepositoryPort over a mapping of target -> path -> answer: the bytes,
    or the Refused or TimedOut the test scripts for that path. `unlisted`
    scripts the answer to every tree listing, `unlisted_at` to one target's.
    What a change did is told from the two targets' files."""

    def __init__(
        self,
        files: Mapping[Base | Head, Mapping[str, bytes | Refused | TimedOut]],
        *,
        unlisted: Refused | TimedOut | None = None,
        unlisted_at: Mapping[Base | Head, Refused | TimedOut] | None = None,
    ) -> None:
        self._files = files
        self._unlisted = unlisted
        self._unlisted_at = unlisted_at or {}

    def read(
        self, path: str, at: Base | Head, deadline: Deadline | None
    ) -> bytes | Absent | Refused | TimedOut:
        found = self._files.get(at, {}).get(path)
        return Absent(path) if found is None else found

    def tree(
        self, at: Base | Head, deadline: Deadline | None
    ) -> tuple[str, ...] | Refused | TimedOut:
        if self._unlisted is not None:
            return self._unlisted
        if at in self._unlisted_at:
            return self._unlisted_at[at]
        return tuple(sorted(self._files.get(at, {})))

    def changed(
        self, base: Base, head: Head, deadline: Deadline | None
    ) -> ChangedPaths | Refused | TimedOut:
        before = self._files.get(base, {})
        after = self._files.get(head, {})
        return ChangedPaths(
            created=tuple(sorted(set(after) - set(before))),
            deleted=tuple(sorted(set(before) - set(after))),
            modified=tuple(
                sorted(p for p in set(before) & set(after) if before[p] != after[p])
            ),
        )


def _restricted(model: CodeModel, paths: Collection[str]) -> CodeModel:
    """The facts of the model that sit in one of the paths."""
    return CodeModel(
        units=tuple(u for u in model.units if u.path in paths),
        imports=tuple(e for e in model.imports if e.path in paths),
        definitions=tuple(d for d in model.definitions if d.unit.path in paths),
        references=tuple(r for r in model.references if r.path in paths),
        calls=tuple(c for c in model.calls if c.path in paths),
        accesses=tuple(a for a in model.accesses if a.path in paths),
        writes=tuple(w for w in model.writes if w.path in paths),
        bindings=tuple(b for b in model.bindings if b.path in paths),
        conditionals=tuple(c for c in model.conditionals if c.path in paths),
        members=tuple(m for m in model.members if m.path in paths),
        test_cases=tuple(t for t in model.test_cases if t.path in paths),
        regions=tuple(r for r in model.regions if r.path in paths),
        unparsed=tuple(u for u in model.unparsed if u.path in paths),
    )


class FakeCodeModel:
    """CodeModelPort over facts the test configures: a file unit per source
    (but a source the facts hold Unparsed), plus the facts of those sources,
    each unit re-layered by the declaration. `when` keys facts to a source's
    exact bytes: a source with those bytes takes its facts from there, so one
    path can read differently at two targets. Its clock is frozen at `now`,
    so a deadline at or before it has passed."""

    def __init__(
        self,
        facts: CodeModel | None = None,
        *,
        when: Mapping[bytes, CodeModel] | None = None,
        now: float = 1e9,
    ) -> None:
        self._facts = facts if facts is not None else CodeModel()
        self._when = when or {}
        self._now = now

    def _facts_of(self, sources: Mapping[str, bytes]) -> CodeModel:
        keyed = {path for path, data in sources.items() if data in self._when}
        plain = set(sources) - keyed
        return merged(
            [
                _restricted(self._facts, plain),
                *(_restricted(self._when[sources[p]], {p}) for p in sorted(keyed)),
            ]
        )

    def model(
        self,
        sources: Mapping[str, bytes],
        declaration: Declaration,
        vocabulary: Vocabulary,
        deadline: Deadline | None,
    ) -> CodeModel | TimedOut:
        if deadline is not None and deadline.epoch_seconds <= self._now:
            return TimedOut("model the sources")
        f = self._facts_of(sources)
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
            bindings=tuple(b for b in f.bindings if b.path in sources),
            conditionals=tuple(c for c in f.conditionals if c.path in sources),
            members=tuple(m for m in f.members if m.path in sources),
            test_cases=tuple(t for t in f.test_cases if t.path in sources),
            regions=tuple(r for r in f.regions if r.path in sources),
            unparsed=tuple(u for u in f.unparsed if u.path in sources),
        )


def _relayered(unit: Unit, declaration: Declaration) -> Unit:
    return replace(unit, layer=layer_of(unit.path, unit.start, declaration))


class FakeComplexity:
    """ComplexityPort answering the fixed complexity the test configures, for
    the sources it is handed, or the unavailable or TimedOut answer it
    scripts. Its clock is frozen at `now`, so a deadline at or before it has
    passed."""

    def __init__(
        self,
        answer: tuple[Complexity, ...] | MetricsUnavailable | TimedOut = (),
        *,
        now: float = 1e9,
    ) -> None:
        self._answer = answer
        self._now = now

    def measure(
        self, sources: Mapping[str, bytes], deadline: Deadline | None
    ) -> Metrics | MetricsUnavailable | TimedOut:
        if deadline is not None and deadline.epoch_seconds <= self._now:
            return TimedOut("measure complexity")
        if isinstance(self._answer, MetricsUnavailable | TimedOut):
            return self._answer
        return Metrics(complexity=tuple(c for c in self._answer if c.path in sources))


class FakeDuplication:
    """DuplicationPort answering the fixed clones the test configures, those
    between sources it is handed, or the unavailable or TimedOut answer it
    scripts. Its clock is frozen at `now`, so a deadline at or before it has
    passed."""

    def __init__(
        self,
        answer: tuple[Clone, ...] | MetricsUnavailable | TimedOut = (),
        *,
        now: float = 1e9,
    ) -> None:
        self._answer = answer
        self._now = now

    def measure(
        self, sources: Mapping[str, bytes], deadline: Deadline | None
    ) -> Metrics | MetricsUnavailable | TimedOut:
        if deadline is not None and deadline.epoch_seconds <= self._now:
            return TimedOut("find clones")
        if isinstance(self._answer, MetricsUnavailable | TimedOut):
            return self._answer
        return Metrics(
            clones=tuple(
                c
                for c in self._answer
                if c.first.path in sources and c.second.path in sources
            )
        )


class FakeRecords:
    """RecordsPort over a mapping of target -> the records, the
    RecordsUnavailable or the TimedOut the test scripts for it, so base and
    head can hold different records. A target it does not hold has none.
    `radar` scripts the radar per target the same way. Its clock is frozen
    at `now`, so a deadline at or before it has passed."""

    def __init__(
        self,
        by_target: Mapping[Base | Head, DesignRecords | RecordsUnavailable | TimedOut],
        *,
        radar: Mapping[Base | Head, Radar | RecordsUnavailable | TimedOut]
        | None = None,
        now: float = 1e9,
    ) -> None:
        self._by_target = by_target
        self._radar = radar or {}
        self._now = now

    def records(
        self, at: Base | Head, declaration: Declaration, deadline: Deadline | None
    ) -> DesignRecords | RecordsUnavailable | TimedOut:
        if deadline is not None and deadline.epoch_seconds <= self._now:
            return TimedOut("read the design records")
        return self._by_target.get(
            at, RecordsUnavailable("no design record at this target")
        )

    def radar(
        self, at: Base | Head, declaration: Declaration, deadline: Deadline | None
    ) -> Radar | RecordsUnavailable | TimedOut:
        if deadline is not None and deadline.epoch_seconds <= self._now:
            return TimedOut("read the radar")
        return self._radar.get(at, RecordsUnavailable("no radar at this target"))


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


class FakeReviews:
    """ReviewPort over a mapping of commit -> the answer the test scripts;
    a commit it does not hold is Unknown."""

    def __init__(
        self,
        answers: Mapping[
            str, Landing | NoLandingPR | Unknown | ReviewsUnavailable | TimedOut
        ]
        | None = None,
    ) -> None:
        self._answers = answers or {}

    def approvals(
        self, commit: str, deadline: Deadline | None
    ) -> Landing | NoLandingPR | Unknown | ReviewsUnavailable | TimedOut:
        return self._answers.get(commit, Unknown(NO_REVIEWS))
