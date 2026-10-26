"""ReportStore's contract, written once and run against every adapter.

A subclass supplies `store_with`: a store over a fresh place under
tmp_path whose clock reads `now`.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from adherence.domain.coverage import Coverage
from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.finding import Evidence, Finding, Notice, Provenance
from adherence.domain.model import Layer, Unit, UnitKind
from adherence.domain.qualities import catalog_check
from adherence.domain.report import BodyDigest, Report, ReportIdentity, Verdict
from adherence.ports.report_store import ReportStore, StoreMiss

NOW = 1e9
REVISION = "a" * 40
UNIT = Unit("src/app/domain/rules.py", UnitKind.FUNCTION, "tidy", 2, 3, Layer.DOMAIN)
FINDING = Finding(
    catalog_check("Stub"),
    UNIT,
    Layer.DOMAIN,
    "pass",
    Evidence(UNIT.path, 2, "def tidy():"),
    provenance=Provenance.INTRODUCED,
)
IDENTITY = ReportIdentity("0.1.0", "p" * 64, "d" * 64, ("python",), "unasked")
REPORT = Report(
    ran=(catalog_check("Stub"), catalog_check("Grep")),
    findings=(FINDING,),
    notices=(Notice("exemption added: inert for this change"),),
    coverage=(Coverage("timed out", check="Arrow", path="src/a.py"),),
    units=(UNIT, replace(UNIT, kind=UnitKind.FILE, symbol=None, layer=None)),
    verdict=Verdict.LOWERED,
    reasons=("Stub did not run on src/a.py",),
    removed=(
        replace(FINDING, provenance=None, reached=Layer.ADAPTERS, exempt="a reason"),
    ),
    bodies=(BodyDigest(UNIT.path, "tidy", "b" * 64),),
    identity=IDENTITY,
    repository="example",
    revision=REVISION,
)


class ReportStoreContract:
    def store_with(self, tmp_path: Path, *, now: float = NOW) -> ReportStore:
        raise NotImplementedError("a contract subclass supplies its adapter")

    def test_a_report_put_is_got_back_whole(self, tmp_path: Path) -> None:
        """Given a report put under its repository, revision and identity,
        When it is got by those, Then the same report comes back."""
        store = self.store_with(tmp_path)

        recorded = store.put(REPORT)

        assert recorded.kept, recorded
        assert store.get("example", REVISION, IDENTITY.digest, None) == REPORT

    def test_a_report_under_another_identity_is_a_miss(self, tmp_path: Path) -> None:
        """Given a report kept under one identity, When another identity is
        asked for, Then the answer is a miss."""
        store = self.store_with(tmp_path)
        store.put(REPORT)
        other = replace(IDENTITY, judge="available")

        assert isinstance(store.get("example", REVISION, other.digest, None), StoreMiss)

    def test_a_revision_named_by_a_moving_name_is_never_looked_up(
        self, tmp_path: Path
    ) -> None:
        """Given a report of a revision named `HEAD`, When it is put and then
        asked for by that name, Then it is kept for the scan but the answer is
        a miss: a name that moves never keys a base."""
        store = self.store_with(tmp_path)

        recorded = store.put(replace(REPORT, revision="HEAD"))

        assert recorded.kept
        assert isinstance(
            store.get("example", "HEAD", IDENTITY.digest, None), StoreMiss
        )

    def test_a_report_with_no_identity_is_not_kept(self, tmp_path: Path) -> None:
        """Given a report that names no identity, When it is put, Then it is
        not kept and the notice says why."""
        store = self.store_with(tmp_path)

        recorded = store.put(replace(REPORT, identity=None))

        assert not recorded.kept
        assert recorded.notice is not None and recorded.notice.message

    def test_a_passed_deadline_times_out_a_get(self, tmp_path: Path) -> None:
        """Given a deadline already passed, When a report is got, Then the
        answer is TimedOut."""
        store = self.store_with(tmp_path)
        store.put(REPORT)

        answer = store.get("example", REVISION, IDENTITY.digest, Deadline(NOW - 1))

        assert isinstance(answer, TimedOut)
