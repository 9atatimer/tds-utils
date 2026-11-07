"""adapters/fakes.py -- an in-memory adapter per port, for tests only.

container.py never imports this module; a test passes these in. Each
deadline-bound fake is scriptable to answer TimedOut.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import (
    DECLARATION_PATH,
    Declaration,
    Landing,
    NoLandingPR,
    ReviewsUnavailable,
    Unknown,
    layer_of,
)
from adherence.domain.finding import Notice
from adherence.domain.model import (
    Clone,
    CodeModel,
    Complexity,
    Metrics,
    MetricsUnavailable,
    Unit,
    UnitKind,
    merged,
    within,
)
from adherence.domain.parameters import Vocabulary
from adherence.domain.questions import (
    Availability,
    Decision,
    Rejected,
    Schema,
    State,
    Unavailable,
)
from adherence.domain.records import DesignRecords, Radar, RecordsUnavailable
from adherence.domain.report import Recorded, Report
from adherence.domain.target import Base, ChangedPaths, Head, Rename, is_object_id
from adherence.ports.decision import Decided
from adherence.ports.report_store import StoreMiss
from adherence.ports.repository import Absent, Refused

NO_REVIEWS = "the fake reviews know no landing of this commit"


class FakeRepository:
    """RepositoryPort over a mapping of target -> path -> answer: the bytes,
    or the Refused or TimedOut the test scripts for that path. `unlisted`
    scripts the answer to every tree listing, `unlisted_at` to one target's.
    `history` scripts the commits that changed each path, newest first, or
    the Refused or TimedOut its listing answers. `reads` keeps every read
    it was asked for, in order, as (path, target).
    What a change did is told from the two targets' files: a path gone and
    one come with the same bytes is a rename. Its clock is frozen at `now`,
    the epoch unless the test sets it, so a deadline at or before it has
    passed and every method answers TimedOut. `asked` lists every call, by
    method and target, in order. `unfound_at` scripts the answer to `find`
    at a target."""

    def __init__(
        self,
        files: Mapping[Base | Head, Mapping[str, bytes | Refused | TimedOut]],
        *,
        unlisted: Refused | TimedOut | None = None,
        unlisted_at: Mapping[Base | Head, Refused | TimedOut] | None = None,
        history: Mapping[str, tuple[str, ...] | Refused | TimedOut] | None = None,
        unfound_at: Mapping[Base | Head, Refused | TimedOut] | None = None,
        now: float = 0.0,
    ) -> None:
        self._files = files
        self._unfound_at = unfound_at or {}
        self._unlisted = unlisted
        self._unlisted_at = unlisted_at or {}
        self._history = history or {}
        self.reads: list[tuple[str, Base | Head]] = []
        self._now = now
        self.asked: list[tuple[str, Base | Head]] = []

    def _passed(self, deadline: Deadline | None) -> bool:
        return deadline is not None and deadline.epoch_seconds <= self._now

    def read(
        self, path: str, at: Base | Head, deadline: Deadline | None
    ) -> bytes | Absent | Refused | TimedOut:
        self.reads.append((path, at))
        self.asked.append(("read", at))
        if self._passed(deadline):
            return TimedOut(f"read {path}")
        found = self._files.get(at, {}).get(path)
        return Absent(path) if found is None else found

    def tree(
        self, at: Base | Head, deadline: Deadline | None
    ) -> tuple[str, ...] | Refused | TimedOut:
        self.asked.append(("tree", at))
        if self._passed(deadline):
            return TimedOut("list the tree")
        if self._unlisted is not None:
            return self._unlisted
        if at in self._unlisted_at:
            return self._unlisted_at[at]
        return tuple(sorted(self._files.get(at, {})))

    def history(
        self, path: str, base: Base, deadline: Deadline | None
    ) -> tuple[str, ...] | Refused | TimedOut:
        self.asked.append(("history", base))
        if self._passed(deadline):
            return TimedOut(f"list the history of {path}")
        return self._history.get(path, ())

    def find(
        self, name: str, at: Base | Head, deadline: Deadline | None
    ) -> tuple[str, ...] | Refused | TimedOut:
        """The target's files with the name, read from its files whatever
        `unlisted` scripts for the tree listing."""
        self.asked.append(("find", at))
        if self._passed(deadline):
            return TimedOut(f"find every {name}")
        if at in self._unfound_at:
            return self._unfound_at[at]
        return tuple(
            sorted(p for p in self._files.get(at, {}) if p.rpartition("/")[2] == name)
        )

    def touched(
        self, name: str, base: Base, deadline: Deadline | None
    ) -> tuple[str, ...] | Refused | TimedOut:
        """The paths with the name that `history` scripts."""
        self.asked.append(("touched", base))
        if self._passed(deadline):
            return TimedOut(f"list the history of every {name}")
        return tuple(sorted(p for p in self._history if p.rpartition("/")[2] == name))

    def changed(
        self, base: Base, head: Head, deadline: Deadline | None
    ) -> ChangedPaths | Refused | TimedOut:
        self.asked.append(("changed", head))
        if self._passed(deadline):
            return TimedOut("tell what the change did")
        before = self._files.get(base, {})
        after = self._files.get(head, {})
        gone = sorted(set(before) - set(after))
        come = sorted(set(after) - set(before))
        renamed = [
            Rename(old, new)
            for old in gone
            for new in come
            if before[old] == after[new]
            and [n for n in come if after[n] == before[old]] == [new]
            and [o for o in gone if before[o] == after[new]] == [old]
        ]
        return ChangedPaths(
            created=tuple(p for p in come if p not in {r.new for r in renamed}),
            deleted=tuple(p for p in gone if p not in {r.old for r in renamed}),
            modified=tuple(
                sorted(p for p in set(before) & set(after) if before[p] != after[p])
            ),
            renamed=tuple(renamed),
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
                within(self._facts, plain),
                *(within(self._when[sources[p]], {p}) for p in sorted(keyed)),
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
    passed. `asked` counts its calls."""

    def __init__(
        self,
        answer: tuple[Complexity, ...] | MetricsUnavailable | TimedOut = (),
        *,
        now: float = 1e9,
    ) -> None:
        self._answer = answer
        self._now = now
        self.asked = 0

    def measure(
        self, sources: Mapping[str, bytes], deadline: Deadline | None
    ) -> Metrics | MetricsUnavailable | TimedOut:
        self.asked += 1
        if deadline is not None and deadline.epoch_seconds <= self._now:
            return TimedOut("measure complexity")
        if isinstance(self._answer, MetricsUnavailable | TimedOut):
            return self._answer
        return Metrics(complexity=tuple(c for c in self._answer if c.path in sources))


class FakeDuplication:
    """DuplicationPort answering the fixed clones the test configures, those
    between sources it is handed, or the unavailable or TimedOut answer it
    scripts. Its clock is frozen at `now`, so a deadline at or before it has
    passed. `asked` counts its calls."""

    def __init__(
        self,
        answer: tuple[Clone, ...] | MetricsUnavailable | TimedOut = (),
        *,
        now: float = 1e9,
    ) -> None:
        self._answer = answer
        self._now = now
        self.asked = 0

    def measure(
        self, sources: Mapping[str, bytes], deadline: Deadline | None
    ) -> Metrics | MetricsUnavailable | TimedOut:
        self.asked += 1
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
    `radar` scripts the radar per target the same way. `by_record` scripts
    the records by the design record the declaration names -- keyed by its
    path, or by (target, path) to tell base from head -- so two
    sub-projects can name two records; `by_radar` scripts the radar by the
    radar path named. Its clock is frozen at `now`, so a deadline at or
    before it has passed. `asked` lists every call, by method and target,
    in order; `named` every call with the record or radar path it named."""

    def __init__(
        self,
        by_target: Mapping[Base | Head, DesignRecords | RecordsUnavailable | TimedOut],
        *,
        radar: Mapping[Base | Head, Radar | RecordsUnavailable | TimedOut]
        | None = None,
        by_record: Mapping[
            str | tuple[Base | Head, str], DesignRecords | RecordsUnavailable | TimedOut
        ]
        | None = None,
        by_radar: Mapping[str, Radar | RecordsUnavailable | TimedOut] | None = None,
        now: float = 1e9,
    ) -> None:
        self._by_target = by_target
        self._radar = radar or {}
        self._by_record = by_record or {}
        self._by_radar = by_radar or {}
        self._now = now
        self.asked: list[tuple[str, Base | Head]] = []
        self.named: list[tuple[str, Base | Head, str | None]] = []

    def records(
        self, at: Base | Head, declaration: Declaration, deadline: Deadline | None
    ) -> DesignRecords | RecordsUnavailable | TimedOut:
        self.asked.append(("records", at))
        if deadline is not None and deadline.epoch_seconds <= self._now:
            return TimedOut("read the design records")
        named = declaration.records
        self.named.append(("records", at, named.design if named else None))
        if named is not None:
            for key in ((at, named.design), named.design):
                if key in self._by_record:
                    return self._by_record[key]
        return self._by_target.get(
            at, RecordsUnavailable("no design record at this target")
        )

    def radar(
        self, at: Base | Head, declaration: Declaration, deadline: Deadline | None
    ) -> Radar | RecordsUnavailable | TimedOut:
        self.asked.append(("radar", at))
        if deadline is not None and deadline.epoch_seconds <= self._now:
            return TimedOut("read the radar")
        self.named.append(("radar", at, declaration.radar))
        if declaration.radar is not None and declaration.radar in self._by_radar:
            return self._by_radar[declaration.radar]
        return self._radar.get(at, RecordsUnavailable("no radar at this target"))


class FakeDecision:
    """DecisionPort answering each question of a schema with the probabilities
    the test scripts for its question id -- or, for a unit whose symbol
    `per_symbol` names, those scripted there -- and a question nothing
    scripts with an even spread over its options. A question id in
    `uncalibrated` is answered label-only. `answers` may instead script one
    failure, Unavailable, Rejected or TimedOut, for every schema. A schema
    with no question is Rejected, as the decide client rejects it. Its clock
    is frozen at `now`, so a deadline at or before it has passed. It keeps
    every state and schema it was asked about, in order."""

    def __init__(
        self,
        answers: Mapping[str, Mapping[str, float]] | Unavailable | Rejected | TimedOut,
        *,
        per_symbol: Mapping[str, Mapping[str, Mapping[str, float]]] | None = None,
        uncalibrated: frozenset[str] = frozenset(),
        now: float = 1e9,
    ) -> None:
        self._answers = answers
        self._per_symbol = per_symbol or {}
        self._uncalibrated = uncalibrated
        self._now = now
        self.asked: list[tuple[State, Schema]] = []

    def availability(self) -> Availability:
        """A bound judge; a scripted Unavailable is one that cannot be
        reached."""
        return Availability.AVAILABLE

    def decide(
        self, state: State, schema: Schema, deadline: Deadline | None
    ) -> Decided:
        if deadline is not None and deadline.epoch_seconds <= self._now:
            return TimedOut("ask the judge")
        self.asked.append((state, schema))
        if isinstance(self._answers, Unavailable | Rejected | TimedOut):
            return self._answers
        if not schema.questions:
            return Rejected("a schema with no question")
        scripted = {
            **self._answers,
            **self._per_symbol.get(state.unit.symbol or "", {}),
        }
        return Decision(
            {
                key: scripted.get(
                    question.id,
                    {o: 1.0 / len(question.options) for o in question.options},
                )
                for key, question in schema.questions.items()
            },
            uncalibrated=frozenset(
                key
                for key, question in schema.questions.items()
                if question.id in self._uncalibrated
            ),
        )


class FakeReviews:
    """ReviewPort over a mapping of commit -> the answer the test scripts;
    a commit it does not hold is Unknown. `asked` keeps every commit it
    was asked about, in order. Its clock is frozen at `now`, so a deadline
    at or before it has passed."""

    def __init__(
        self,
        answers: Mapping[
            str, Landing | NoLandingPR | Unknown | ReviewsUnavailable | TimedOut
        ]
        | None = None,
        *,
        now: float = 1e9,
    ) -> None:
        self._answers = answers or {}
        self._now = now
        self.asked: list[str] = []

    def approvals(
        self, commit: str, deadline: Deadline | None, *, path: str = DECLARATION_PATH
    ) -> Landing | NoLandingPR | Unknown | ReviewsUnavailable | TimedOut:
        self.asked.append(commit)
        if deadline is not None and deadline.epoch_seconds <= self._now:
            return TimedOut("read the reviews of a landing")
        return self._answers.get(commit, Unknown(NO_REVIEWS))


class FakeReportStore:
    """ReportStore in memory. Every report put is kept for the scan; one of
    a revision named by its object id is also kept for lookup, under its
    repository, revision and identity. `failing` scripts every put to fail
    with that reason. `hits` lists every get that found a report, `asked`
    every get. Its clock is frozen at `now`, so a deadline at or before it
    has passed."""

    def __init__(self, *, failing: str | None = None, now: float = 1e9) -> None:
        self._kept: dict[tuple[str, str, str], Report] = {}
        self._failing = failing
        self._now = now
        self.scanned: list[Report] = []
        self.hits: list[tuple[str, str]] = []
        self.asked: list[tuple[str, str]] = []

    def get(
        self, repository: str, revision: str, identity: str, deadline: Deadline | None
    ) -> Report | StoreMiss | TimedOut:
        self.asked.append((repository, revision))
        if deadline is not None and deadline.epoch_seconds <= self._now:
            return TimedOut("read a kept report")
        found = self._kept.get((repository, revision, identity))
        if found is None:
            return StoreMiss(f"no report kept for {repository} at {revision}")
        self.hits.append((repository, revision))
        return found

    def put(self, report: Report) -> Recorded:
        if self._failing is not None:
            return Recorded(False, Notice(f"report not kept: {self._failing}"))
        if report.repository is None or report.identity is None:
            return Recorded(
                False, Notice("report not kept: it names no repository or identity")
            )
        self.scanned.append(report)
        if report.revision is not None and is_object_id(report.revision):
            key = (report.repository, report.revision, report.identity.digest)
            self._kept[key] = report
        return Recorded(True)
