"""judge_change, the gate's core (DESIGN.ARCH-ADHERENCE.md, Judging a change
and Behaviors; ARCHITECTURE.ARCH-ADHERENCE.md, Use-case surface), driven
by its signature with a fake behind every port."""

from __future__ import annotations

from dataclasses import replace

from adherence.adapters.fakes import FakeReportStore
from adherence.domain.declaration import DECLARATION_PATH
from adherence.domain.finding import Provenance
from adherence.domain.model import Layer, Parameter, Signature, merged
from adherence.domain.records import (
    Behavior,
    DesignRecords,
    RecordStatus,
    SurfaceRow,
    Term,
    UseCase,
)
from adherence.domain.report import Verdict
from adherence.ports.repository import Refused
from tests import facts_kit as kit
from tests.judge_kit import (
    BASE,
    HEAD,
    REPOSITORY,
    RULES,
    judge_with,
    measured_at,
    stubbed,
)
from tests.measure_kit import HEXAGON

USE = "src/app/application/use.py"
CLEAN = b"def run():\n    return 1\n"
STUBBED = b"\ndef tidy():\n    pass\n"
OLD = b"\ndef tidy():\n    pass\n# old\n"
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


def test_judge_change_deleting_a_flawed_unit_moves_nothing() -> None:
    """Given a change that only deletes units with an existing flaw -- a
    whole file, and a function from a file it keeps -- When it is judged,
    Then neither flaw is introduced or removed and the verdict is held."""
    flawed = b"\ndef tidy():\n    pass\n\ndef keep():\n    return 1\n"
    kept = b"\n\n\n\ndef keep():\n    return 1\n"
    other = "src/app/domain/other.py"
    keep = stubbed(other, "keep", 5, stub=None)

    report = judge_with(
        {RULES: STUBBED, USE: CLEAN, other: flawed},
        {USE: CLEAN, other: kept},
        when={
            **WHEN,
            flawed: merged([stubbed(other, "tidy", 2), keep]),
            kept: keep,
        },
    )

    assert report.findings == ()
    assert (report.removed, report.verdict) == ((), Verdict.HELD)


def test_judge_change_creating_an_undeclared_unit_finds_it() -> None:
    """Given a change that creates a unit no declaration assigns to a layer,
    When Covered runs, Then a finding names the unit and the verdict is
    lowered."""
    loose = "src/app/extra/loose.py"

    report = judge_with({USE: CLEAN}, {USE: CLEAN, loose: CLEAN})

    (finding,) = report.findings
    assert (finding.check.name, finding.unit.path) == ("Covered", loose)
    assert finding.provenance is Provenance.INTRODUCED
    assert report.verdict is Verdict.LOWERED
    assert "Covered" in {c.name for c in report.ran}


WIDENED = HEXAGON.replace(
    b'domain = ["src/app/domain/**"]',
    b'domain = ["src/app/domain/**", "src/app/extra/**"]',
)


def test_judge_change_widening_its_declaration_for_a_created_unit_is_honored() -> None:
    """Given a change that creates a unit and assigns it a layer in its own
    declaration, When the change is judged, Then the unit is checked under
    that layer and Covered finds nothing."""
    loose = "src/app/extra/loose.py"

    report = judge_with(
        {USE: CLEAN},
        {USE: CLEAN, loose: STUBBED, DECLARATION_PATH: WIDENED},
        when={STUBBED: stubbed(loose, "tidy", 2)},
    )

    (finding,) = report.findings
    assert (finding.check.name, finding.unit.path) == ("Stub", loose)
    assert finding.layer is Layer.DOMAIN
    assert "Covered" in {c.name for c in report.ran}


DESIGN = "docs/design/DESIGN.APP.md"


def test_judge_change_removing_a_behavior_and_a_term_finds_the_narrowing() -> None:
    """Given a change that removes a behavior and a term from an approved
    record, When Record kept runs, Then a finding names the record and each
    thing removed, and the verdict is lowered."""
    kept = Behavior("An order is priced", "Given ..., Then ...", DESIGN, 12)
    dropped = Behavior("An order is refunded", "Given ..., Then ...", DESIGN, 13)
    term = Term("Refund", DESIGN, 40)

    report = judge_with(
        {USE: CLEAN},
        {USE: CLEAN},
        records={
            BASE: DesignRecords(behaviors=(kept, dropped), domain_language=(term,)),
            HEAD: DesignRecords(behaviors=(kept,)),
        },
    )

    narrowed = [f for f in report.findings if f.check.name == "Record kept"]
    assert {(f.unit.path, f.subject) for f in narrowed} == {
        (DESIGN, "An order is refunded"),
        (DESIGN, "Refund"),
    }
    assert all(f.provenance is Provenance.INTRODUCED for f in narrowed)
    assert report.verdict is Verdict.LOWERED


def test_judge_change_adding_a_behavior_with_its_use_case_traces_it() -> None:
    """Given a change that adds a behavior to the record and its use case in
    the same change, When Trace runs, Then there is no Trace finding for it:
    the record is read at the head, with its code."""
    architecture = "docs/design/ARCHITECTURE.APP.md"
    order = Parameter("order", None, False, False)
    existing = Behavior(
        "An order is priced",
        "Given an order, When it is priced, Then it has a price",
        DESIGN,
        9,
    )
    added = Behavior(
        "An order is closed",
        "Given an order, When it is closed, Then it is closed",
        DESIGN,
        10,
    )
    priced = (
        UseCase("price", Signature((order,), None), architecture, 12),
        SurfaceRow(existing.name, "price", architecture, 12),
    )
    closed = (
        UseCase("close", Signature((order,), None), architecture, 13),
        SurfaceRow(added.name, "close", architecture, 13),
    )
    both = b"def price(order):\n    return 1\n\ndef close(order):\n    return 2\n"
    facts = kit.facts(
        [
            kit.function(USE, "price", 1, (kit.value("order"),)),
            kit.function(USE, "close", 4, (kit.value("order"),)),
        ]
    )

    report = judge_with(
        {USE: b"def price(order):\n    return 1\n"},
        {USE: both},
        facts=facts,
        records={
            BASE: DesignRecords(
                behaviors=(existing,), use_cases=(priced[0],), surface=(priced[1],)
            ),
            HEAD: DesignRecords(
                behaviors=(existing, added),
                use_cases=(priced[0], closed[0]),
                surface=(priced[1], closed[1]),
            ),
        },
    )

    assert "Trace" in {c.name for c in report.ran}
    assert [f for f in report.findings if f.check.name == "Trace"] == []


def test_judge_change_with_a_draft_design_record_reports_it_missing() -> None:
    """Given a declared repository whose design record is in draft, When a
    change is judged, Then Trace, Language, Change, Kept test and Record kept
    report coverage missing and name the record, and the other qualities'
    checks run."""
    architecture = "docs/design/ARCHITECTURE.APP.md"
    behavior = Behavior("An order is priced", "Given x, When y, Then z", DESIGN, 9)
    draft = DesignRecords(
        behaviors=(behavior,),
        statuses=(
            RecordStatus(DESIGN, "DRAFT"),
            RecordStatus(architecture, "APPROVED"),
        ),
    )

    report = judge_with({USE: CLEAN}, {USE: CLEAN}, records={BASE: draft, HEAD: draft})

    reasons = {c.check: c.reason for c in report.coverage if c.check}
    for check in ("Trace", "Language", "Change", "Kept test", "Record kept"):
        assert DESIGN in reasons.get(check, ""), check
    assert {"Grep", "Stub", "Covered"} <= {c.name for c in report.ran}


def test_judge_change_after_a_landed_cover_marks_its_flaws_existing() -> None:
    """Given a declaration edit that covers an existing unit, landed in one
    change, When the next change is judged, Then that unit's flaws are in
    the base's report and marked existing."""
    old = "src/app/extra/old.py"
    landed = {DECLARATION_PATH: WIDENED, old: STUBBED, USE: CLEAN}

    report = judge_with(
        landed,
        {**landed, USE: CLEAN + b"\n# edited\n"},
        when={STUBBED: stubbed(old, "tidy", 2)},
    )

    (finding,) = report.findings
    assert (finding.unit.path, finding.layer) == (old, Layer.DOMAIN)
    assert finding.provenance is Provenance.EXISTING
    assert report.verdict is Verdict.HELD


NARROWED = b"""
[layers]
application = ["src/app/application/**"]
domain = ["src/app/extra/**"]

[[exemptions]]
check = "Stub"
unit = "src/app/domain/rules.py"
reason = "the change says so"
"""


def test_judge_change_cannot_narrow_its_own_declaration() -> None:
    """Given a change whose own declaration removes an assignment, covers an
    existing unit and adds an exemption, When it is judged, Then it is
    judged as if those edits were absent, and each edit is a notice."""
    old = "src/app/extra/old.py"
    base = {RULES: STUBBED, old: OLD, USE: CLEAN}

    report = judge_with(
        base,
        {**base, USE: CLEAN + b"\n# edited\n", DECLARATION_PATH: NARROWED},
        when={**WHEN, OLD: stubbed(old, "tidy", 2)},
    )

    (finding,) = report.findings
    assert (finding.unit.path, finding.layer) == (RULES, Layer.DOMAIN)
    assert finding.provenance is Provenance.EXISTING
    assert report.verdict is Verdict.HELD
    notices = [n.message for n in report.notices]
    assert any("[layers]" in n and "next change" in n for n in notices), notices
    assert any("exemption added" in n and "inert" in n for n in notices), notices


EXEMPT_RULES = (
    b'\n[[exemptions]]\ncheck = "Stub"\nunit = "src/app/domain/rules.py"\n'
    b'reason = "kept until the rewrite"\n'
)


def test_judge_change_adding_an_exemption_for_its_own_flaw_is_still_lowered() -> None:
    """Given a change that adds an exemption for a flaw it introduces, When
    it is judged, Then the flaw lowers the verdict and the exemption is a
    notice."""
    report = judge_with(
        {RULES: FIXED},
        {RULES: STUBBED, DECLARATION_PATH: HEXAGON + EXEMPT_RULES},
        when=WHEN,
    )

    (finding,) = report.findings
    assert finding.provenance is Provenance.INTRODUCED
    assert report.verdict is Verdict.LOWERED
    assert any(
        "exemption added" in n.message and "kept until the rewrite" in n.message
        for n in report.notices
    )
