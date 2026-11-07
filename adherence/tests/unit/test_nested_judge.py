"""judge_change under nested declarations: each file settled in force on
its own, a path under none an undeclared subtree that Covered never names
(DESIGN.ARCH-ADHERENCE.md, Behaviors, An undeclared subtree has no
adherence and A declaration in force is settled per file)."""

from __future__ import annotations

from adherence.adapters.fakes import FakeReviews
from adherence.domain.coverage import UNDECLARED_SUBTREE
from adherence.domain.declaration import NoLandingPR
from adherence.domain.report import Report
from tests.judge_kit import BASE, judge_with

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
