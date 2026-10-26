"""judge_change, the gate's core (DESIGN.ARCH-ADHERENCE.md, Judging a change
and Behaviors; ARCHITECTURE.ARCH-ADHERENCE.md, Use-case surface), driven
by its signature with a fake behind every port."""

from __future__ import annotations

from dataclasses import replace

from adherence.adapters.fakes import FakeReportStore
from adherence.domain.finding import Provenance
from adherence.domain.model import merged
from adherence.domain.report import Verdict
from adherence.ports.repository import Refused
from tests import facts_kit as kit
from tests.judge_kit import BASE, REPOSITORY, RULES, judge_with, measured_at, stubbed

USE = "src/app/application/use.py"
CLEAN = b"def run():\n    return 1\n"
STUBBED = b"\ndef tidy():\n    pass\n"
FIXED = b"\ndef tidy():\n    return 1\n"
WHEN = {
    STUBBED: stubbed(RULES, "tidy", 2),
    FIXED: stubbed(RULES, "tidy", 2, stub=None),
}


def test_judge_change_that_removes_a_finding_is_raised() -> None:
    """Given a base finding absent at the head, on a unit the head still
    covers and a check that ran there and passed, with nothing introduced,
    When the change is judged, Then the verdict is raised and the report
    names the removed finding."""
    report = judge_with(
        {RULES: STUBBED},
        {RULES: FIXED},
        when={
            STUBBED: stubbed(RULES, "tidy", 2),
            FIXED: stubbed(RULES, "tidy", 2, stub=None),
        },
    )

    assert report.verdict is Verdict.RAISED
    (removed,) = report.removed
    assert (removed.check.name, removed.unit.path, removed.unit.symbol) == (
        "Stub",
        RULES,
        "tidy",
    )
    assert report.findings == ()


def test_judge_change_that_introduces_a_finding_is_lowered() -> None:
    """Given a change that introduces a finding, When it is judged, Then the
    verdict is lowered and the report names the finding, marked introduced.
    (A judged finding's confidence is task-064's: no judged check runs yet.)"""
    report = judge_with(
        {RULES: FIXED},
        {RULES: STUBBED},
        when={
            STUBBED: stubbed(RULES, "tidy", 2),
            FIXED: stubbed(RULES, "tidy", 2, stub=None),
        },
    )

    assert report.verdict is Verdict.LOWERED
    (finding,) = report.findings
    assert (finding.check.name, finding.unit.symbol) == ("Stub", "tidy")
    assert finding.provenance is Provenance.INTRODUCED
    assert report.removed == ()


def test_judge_change_bringing_back_a_fixed_flaw_reads_the_stored_base() -> None:
    """Given a base whose stored report, kept under the base identity by an
    earlier run, holds the flaw fixed, When a later change brings the same
    finding back, Then the stored report is the base, the finding is
    introduced and the verdict is lowered, with nothing configured."""
    store = FakeReportStore()
    store.put(replace(measured_at({RULES: FIXED}, when=WHEN), repository=REPOSITORY))

    report = judge_with(
        {RULES: FIXED},
        {RULES: STUBBED},
        when=WHEN,
        store=store,
        unlisted_at={BASE: Refused(".", "the base is not measured again")},
    )

    assert report.verdict is Verdict.LOWERED
    (finding,) = report.findings
    assert finding.provenance is Provenance.INTRODUCED
    assert store.hits == [(REPOSITORY, BASE.revision)]


def test_judge_change_creating_a_failing_unit_marks_it_introduced() -> None:
    """Given a change that creates a unit a rule check fails, When it is
    judged, Then the verdict is lowered and the finding is marked introduced."""
    report = judge_with({USE: CLEAN}, {USE: CLEAN, RULES: STUBBED}, when=WHEN)

    assert report.verdict is Verdict.LOWERED
    (finding,) = report.findings
    assert (finding.check.name, finding.unit.path) == ("Stub", RULES)
    assert finding.provenance is Provenance.INTRODUCED


def test_judge_change_beside_a_known_flaw_marks_it_existing_and_holds() -> None:
    """Given a finding present in the base's report and a change that edits
    another unit, When the change is judged, Then the finding is marked
    existing and the verdict is not lowered by it."""
    report = judge_with(
        {RULES: STUBBED, USE: CLEAN},
        {RULES: STUBBED, USE: CLEAN + b"\n# edited\n"},
        when=WHEN,
    )

    (finding,) = report.findings
    assert finding.provenance is Provenance.EXISTING
    assert report.verdict is Verdict.HELD


def test_judge_change_deleting_a_fake_introduces_the_ports_finding() -> None:
    """Given a change that deletes the fake behind a port and does not edit
    the port, When it is judged, Then the new Swap finding on the port is
    marked introduced and the verdict is lowered."""
    fakes = "tests/fakes.py"
    facts = kit.facts(
        [
            *kit.port(kit.STORE, "Store", 1),
            kit.type_(fakes, "FakeStore", 1),
            kit.function(fakes, "FakeStore.save", 2, parent="FakeStore"),
        ]
    )
    port = b"class Store(Protocol):\n    def save(self): ...\n"
    fake = b"class FakeStore:\n    def save(self): return 1\n"

    report = judge_with({kit.STORE: port, fakes: fake}, {kit.STORE: port}, facts=facts)

    (finding,) = report.findings
    assert (finding.check.name, finding.unit.path) == ("Swap", kit.STORE)
    assert finding.provenance is Provenance.INTRODUCED
    assert report.verdict is Verdict.LOWERED


def test_judge_change_renaming_a_flawed_file_introduces_nothing() -> None:
    """Given a file with an existing flaw that the change moves and does not
    edit, When the change is judged, Then its finding is marked existing and
    keeps its identity, and nothing is removed."""
    policy = "src/app/domain/policy.py"
    facts = merged([stubbed(RULES, "tidy", 2), stubbed(policy, "tidy", 2)])
    base = judge_with({RULES: STUBBED}, {RULES: STUBBED}, facts=facts)

    report = judge_with({RULES: STUBBED}, {policy: STUBBED}, facts=facts)

    (finding,) = report.findings
    assert finding.unit.path == policy
    assert finding.provenance is Provenance.EXISTING
    assert finding.identity == base.findings[0].identity
    assert (report.removed, report.verdict) == ((), Verdict.HELD)


def test_judge_change_renaming_a_flawed_function_introduces_nothing() -> None:
    """Given a function with an existing flaw that the change renames and
    does not otherwise edit, When the change is judged, Then its finding is
    marked existing and nothing is removed."""
    renamed = b"\ndef neat():\n    pass\n"

    report = judge_with(
        {RULES: STUBBED},
        {RULES: renamed},
        when={STUBBED: stubbed(RULES, "tidy", 2), renamed: stubbed(RULES, "neat", 2)},
    )

    (finding,) = report.findings
    assert finding.unit.symbol == "neat"
    assert finding.provenance is Provenance.EXISTING
    assert (report.removed, report.verdict) == ((), Verdict.HELD)


def test_judge_change_deleting_only_clean_code_moves_nothing() -> None:
    """Given a change that only deletes units with no findings, in a
    repository with existing flaws, When it is judged, Then nothing is
    introduced or removed and the verdict is held."""
    report = judge_with({RULES: STUBBED, USE: CLEAN}, {RULES: STUBBED}, when=WHEN)

    assert [f.provenance for f in report.findings] == [Provenance.EXISTING]
    assert (report.removed, report.verdict) == ((), Verdict.HELD)
