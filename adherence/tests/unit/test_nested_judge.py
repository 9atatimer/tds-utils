"""judge_change under nested declarations: each file settled in force on
its own, a path under none an undeclared subtree that Covered never names
(DESIGN.ARCH-ADHERENCE.md, Behaviors, An undeclared subtree has no
adherence and A declaration in force is settled per file)."""

from __future__ import annotations

from adherence.adapters.fakes import FakeRecords, FakeReviews
from adherence.domain.coverage import UNDECLARED_SUBTREE
from adherence.domain.declaration import NoLandingPR
from adherence.domain.model import (
    Body,
    CodeModel,
    Definition,
    Parameter,
    Signature,
    Unit,
    UnitKind,
)
from adherence.domain.records import Behavior, DesignRecords, Seam, SeamKind, Term
from adherence.domain.report import Report
from adherence.ports.repository import Refused
from tests.judge_kit import BASE, HEAD, judge_with
from tests.measure_kit import HEXAGON

SUB = b"""
[layers]
domain = ["src/domain/**"]
"""
CLEAN = b"x = 1\n"
EARLIER = "e" * 40
DELETION = "d" * 40


def _covered(report: Report) -> list[str]:
    return [f.unit.path for f in report.findings if f.check.name == "Covered"]


def _undeclared(report: Report) -> list[str]:
    return sorted(
        c.path or "" for c in report.coverage if c.reason == UNDECLARED_SUBTREE
    )


def _notices(report: Report) -> list[str]:
    return [n.message for n in report.notices]


def test_a_unit_created_in_an_undeclared_subtree_draws_no_covered_finding() -> None:
    """Given a declaration in pkg-a only and a change that creates a file in
    pkg-c, which has none, When the change is judged, Then Covered finds
    nothing, the file is one undeclared-subtree coverage line, and a notice
    names the new undeclared directory."""
    base = {"pkg-a/adherence.toml": SUB, "pkg-a/src/domain/r.py": CLEAN}

    report = judge_with(
        base,
        {**base, "pkg-c/tool.py": CLEAN},
        root=None,
        histories={"pkg-a/adherence.toml": (BASE.revision,)},
    )

    assert _covered(report) == []
    assert _undeclared(report) == ["pkg-c/tool.py"]
    assert "created under no declaration: pkg-c" in _notices(report)


def test_a_unit_created_in_a_declared_subtree_in_no_layer_is_covered() -> None:
    """Given a declaration in pkg-a and a change that creates a pkg-a file no
    layer covers, When the change is judged, Then Covered names it."""
    base = {"pkg-a/adherence.toml": SUB, "pkg-a/src/domain/r.py": CLEAN}

    report = judge_with(
        base,
        {**base, "pkg-a/scripts/run.py": CLEAN},
        root=None,
        histories={"pkg-a/adherence.toml": (BASE.revision,)},
    )

    assert _covered(report) == ["pkg-a/scripts/run.py"]
    assert _undeclared(report) == []


def test_a_declaration_in_force_is_settled_per_file() -> None:
    """Given two sub-project declarations of which only a's has a landing
    that counts, When a change creating a domain file in each is judged,
    Then a's governs, b's is a notice naming it, and b's new file is an
    undeclared subtree that Covered never names."""
    base = {
        "a/adherence.toml": SUB,
        "b/adherence.toml": SUB,
        "a/src/domain/r.py": CLEAN,
    }

    report = judge_with(
        base,
        {**base, "a/src/domain/new.py": CLEAN, "b/scripts/new.py": CLEAN},
        root=None,
        histories={
            "a/adherence.toml": (BASE.revision,),
            "b/adherence.toml": (EARLIER,),
        },
        reviews=FakeReviews({EARLIER: NoLandingPR(EARLIER)}),
    )

    assert _covered(report) == []
    assert _undeclared(report) == ["b/adherence.toml", "b/scripts/new.py"]
    assert any(
        "b/adherence.toml" in n and "not in force" in n for n in _notices(report)
    )
    assert any(c.path == "b/adherence.toml" for c in report.coverage)
    assert "a/src/domain/new.py" in {u.path for u in report.units}


def test_a_declaration_new_at_the_head_governs_from_the_next_change() -> None:
    """Given a change that adds pkg-c/adherence.toml and a file it would
    assign, When the change is judged, Then the file is an undeclared
    subtree for this change, Covered finds nothing, and a notice says the
    new declaration governs from the next change."""
    base = {"pkg-a/adherence.toml": SUB, "pkg-a/src/domain/r.py": CLEAN}

    report = judge_with(
        base,
        {**base, "pkg-c/adherence.toml": SUB, "pkg-c/src/domain/x.py": CLEAN},
        root=None,
        histories={"pkg-a/adherence.toml": (BASE.revision,)},
    )

    assert _covered(report) == []
    assert "pkg-c/src/domain/x.py" in _undeclared(report)
    assert "pkg-c/adherence.toml: a new declaration governs from the next change" in (
        _notices(report)
    )


def test_an_unapproved_deletion_leaves_the_last_approved_revision_in_force() -> None:
    """Given a sub-project declaration deleted by a landing that does not
    count, its earlier landing counted, When a change creating a file there
    in no layer is judged, Then the earlier revision still governs, so
    Covered names the file."""
    base = {"pkg/src/domain/r.py": CLEAN}

    report = judge_with(
        base,
        {**base, "pkg/scripts/run.py": CLEAN},
        root=None,
        histories={"pkg/adherence.toml": (DELETION, EARLIER)},
        reviews=FakeReviews({DELETION: NoLandingPR(DELETION)}),
        landed={EARLIER: {"pkg/adherence.toml": SUB}},
    )

    assert _covered(report) == ["pkg/scripts/run.py"]


def test_an_approved_deletion_ends_the_files_governance() -> None:
    """Given a sub-project declaration whose deletion landed and counts,
    When a change creating a file there is judged, Then nothing governs it:
    it is an undeclared subtree and Covered finds nothing, while a sibling
    declaration still governs its own."""
    base = {"pkg/src/domain/r.py": CLEAN, "lib/adherence.toml": SUB}

    report = judge_with(
        base,
        {**base, "pkg/scripts/run.py": CLEAN},
        root=None,
        histories={
            "pkg/adherence.toml": (DELETION, EARLIER),
            "lib/adherence.toml": (BASE.revision,),
        },
        landed={EARLIER: {"pkg/adherence.toml": SUB}},
    )

    assert _covered(report) == []
    assert "pkg/scripts/run.py" in _undeclared(report)


def test_an_edit_to_a_sub_project_declaration_is_a_notice_naming_it() -> None:
    """Given a change that edits an existing sub-project declaration's
    layers for an existing file, When it is judged, Then the edit is a
    notice naming that file."""
    base = {"pkg/adherence.toml": SUB, "pkg/lib/r.py": CLEAN}

    report = judge_with(
        base,
        {**base, "pkg/adherence.toml": SUB + b'adapters = ["lib/**"]\n'},
        root=None,
        histories={"pkg/adherence.toml": (BASE.revision,)},
    )

    assert any(
        n.startswith("pkg/adherence.toml: [layers] edited") for n in _notices(report)
    ), _notices(report)


def test_a_fixture_declaration_under_the_test_layer_is_never_settled() -> None:
    """Given a root declaration placing tests/** in the test layer, in force,
    and an unreadable fixture adherence.toml under it with landings of its
    own, When a change is judged, Then the fixture is neither in force, nor
    a notice, nor coverage: the root alone governs."""
    root = b'[layers]\ntest = ["tests/**"]\ndomain = ["src/domain/**"]\n'
    fixture = "tests/fixtures/broken/adherence.toml"
    base = {fixture: b"[layers\n", "src/domain/r.py": CLEAN}

    report = judge_with(
        base,
        {**base, "src/domain/new.py": CLEAN},
        root=root,
        histories={fixture: (BASE.revision,)},
    )

    assert report.not_run_reason is None, report.not_run_reason
    assert not any(fixture in n for n in _notices(report)), _notices(report)
    assert not any(c.path == fixture for c in report.coverage)


def test_a_head_whose_declarations_cannot_be_listed_is_one_notice() -> None:
    """Given a declaration in force and a head whose declaration files
    cannot be listed, When the change is judged, Then the one notice about
    the head's declarations says they cannot be read, and no file in force
    is told deleted."""
    base = {"src/app/domain/rules.py": CLEAN}

    report = judge_with(
        base,
        {**base, "src/app/domain/new.py": CLEAN},
        unfound_at={HEAD: Refused(".", "the index is locked")},
    )

    about = [n for n in _notices(report) if "declaration" in n or "deleted" in n]
    assert about == [
        "the change's own declaration cannot be read: . refused: the index is "
        "locked; it is judged under the declaration in force"
    ], _notices(report)


def test_a_deleted_declaration_with_no_counted_landing_leaves_the_files_above() -> None:
    """Given a root declaration in force and a sub-project declaration since
    deleted, neither of whose two landings counted, When a change is
    judged, Then the root governs the subtree: no "judged undeclared"
    notice and no coverage line for the deleted file, and one notice says
    it was deleted with no counted landing."""
    report = judge_with(
        {"pkg/src/r.py": CLEAN},
        {"pkg/src/r.py": CLEAN, "src/app/domain/new.py": CLEAN},
        histories={"pkg/adherence.toml": (DELETION, EARLIER)},
        reviews=FakeReviews(
            {DELETION: NoLandingPR(DELETION), EARLIER: NoLandingPR(EARLIER)}
        ),
        landed={EARLIER: {"pkg/adherence.toml": SUB}},
    )

    notices = _notices(report)
    assert not any("judged undeclared" in n for n in notices), notices
    assert not any(c.path == "pkg/adherence.toml" for c in report.coverage)
    assert (
        "pkg/adherence.toml: deleted with no counted landing; the declarations "
        "above govern its subtree"
    ) in notices


def test_a_creation_under_no_declaration_names_its_own_directory() -> None:
    """Given ops/a/adherence.toml declared and a change that creates
    ops/b/tool.py, When the change is judged, Then the notice names ops/b,
    not ops, which holds the governed ops/a."""
    base = {"ops/a/adherence.toml": SUB, "ops/a/src/domain/r.py": CLEAN}

    report = judge_with(
        base,
        {**base, "ops/b/tool.py": CLEAN, "top.py": CLEAN},
        root=None,
        histories={"ops/a/adherence.toml": (BASE.revision,)},
    )

    created = sorted(n for n in _notices(report) if n.startswith("created under"))
    assert created == [
        "created under no declaration: .",
        "created under no declaration: ops/b",
    ], _notices(report)


def test_a_nested_files_landings_are_asked_for_with_its_own_path() -> None:
    """Given a root declaration and a sub-project one, each with a landing,
    When a change is judged, Then the reviews are asked about each landing
    with that file's own path, so the reviewed text is read from it."""
    reviews = FakeReviews()

    judge_with(
        {"pkg/adherence.toml": SUB, "pkg/src/domain/r.py": CLEAN},
        {"pkg/adherence.toml": SUB, "pkg/src/domain/r.py": CLEAN},
        histories={"pkg/adherence.toml": (EARLIER,)},
        reviews=reviews,
        landed={EARLIER: {"pkg/adherence.toml": SUB}},
    )

    assert (EARLIER, "pkg/adherence.toml") in reviews.asked_for, reviews.asked_for
    assert (BASE.revision, "adherence.toml") in reviews.asked_for


ROOT_RECORDS = (
    HEXAGON + b'\n[records]\ndesign = "docs/D.md"\narchitecture = "docs/A.md"\n'
)
CHILD_RECORDS = b"""
[layers]
application = ["src/application/**"]
ports = ["src/ports/**"]

[override.records]
design = "D.md"
architecture = "A.md"
"""
ROOT_USE = "src/app/application/close.py"
CHILD_USE = "sub/src/application/close.py"


def _scoped(design: str, architecture: str, *, kept: bool) -> DesignRecords:
    """A record pair defining the term Order, naming the port Store, and,
    when `kept`, stating one behavior."""
    return DesignRecords(
        behaviors=(Behavior("An order closes", "Given, When, Then", design, 9),)
        if kept
        else (),
        domain_language=(Term("Order", design, 20),) if design == "docs/D.md" else (),
        seams=(Seam("Store", SeamKind.PORT, architecture, 30),),
    )


def _use_case(path: str) -> Definition:
    unit = Unit(path, UnitKind.FUNCTION, "close", 1, 2, None)
    return Definition(
        unit,
        Signature((Parameter("order", "Order", False, False),), None),
        Body("return order", (), ()),
        (),
        (),
        None,
        False,
    )


def _port(path: str) -> Definition:
    unit = Unit(path, UnitKind.TYPE, "Store", 1, 2, None)
    return Definition(unit, None, Body("...", (), ()), (), (), None, False)


def test_each_records_scope_is_judged_against_its_own_record() -> None:
    """Given a root declaration and a sub-project overriding its records,
    the root's record defining Order and both naming the port Store, which
    only the root's code defines, and the sub-project's record losing a
    behavior at the head, When the change is judged, Then Change finds
    only the sub-project's Store missing, Language only the sub-project's
    Order undefined, and Record kept only the sub-project's lost behavior."""
    files = {
        "sub/adherence.toml": CHILD_RECORDS,
        ROOT_USE: CLEAN,
        "src/app/ports/store.py": CLEAN,
        CHILD_USE: CLEAN,
    }
    facts = CodeModel(
        units=(),
        definitions=(
            _use_case(ROOT_USE),
            _use_case(CHILD_USE),
            _port("src/app/ports/store.py"),
        ),
    )
    records = FakeRecords(
        {},
        by_record={
            "docs/D.md": _scoped("docs/D.md", "docs/A.md", kept=True),
            (BASE, "sub/D.md"): _scoped("sub/D.md", "sub/A.md", kept=True),
            (HEAD, "sub/D.md"): _scoped("sub/D.md", "sub/A.md", kept=False),
        },
    )

    report = judge_with(
        files,
        files,
        facts=facts,
        root=ROOT_RECORDS,
        histories={"sub/adherence.toml": (BASE.revision,)},
        records_port=records,
    )

    def found(check: str) -> list[str]:
        return sorted(
            f"{f.unit.path}:{f.subject}"
            for f in report.findings
            if f.check.name == check
        )

    assert found("Change") == ["sub/A.md:Store: no port"], found("Change")
    assert found("Language") == [f"{CHILD_USE}:Order in close"], found("Language")
    assert found("Record kept") == ["sub/D.md:An order closes"], found("Record kept")
