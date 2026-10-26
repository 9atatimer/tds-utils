"""The declaration in force (DESIGN.ARCH-ADHERENCE.md, Behaviors: An
unapproved declaration is not in force; ARCHITECTURE.ARCH-ADHERENCE.md,
Use-case surface), driven through judge_change by its signature: the
newest landed revision of adherence.toml whose landing a code owner
approved, on a commit whose declaration equals the landed one."""

from __future__ import annotations

from adherence.adapters.fakes import FakeReviews
from adherence.domain.declaration import (
    DECLARATION_PATH,
    Approval,
    Landing,
    NoLandingPR,
    ReviewsUnavailable,
)
from adherence.domain.finding import Provenance
from adherence.domain.report import Report, Verdict
from tests.judge_kit import BASE, RULES, judge_with, stubbed
from tests.measure_kit import HEXAGON

STUBBED = b"\ndef tidy():\n    pass\n"
FIXED = b"\ndef tidy():\n    return 1\n"
WHEN = {
    STUBBED: stubbed(RULES, "tidy", 2),
    FIXED: stubbed(RULES, "tidy", 2, stub=None),
}
# The newest landing (the base's own commit) adds an exemption for the flaw
# the change introduces; the landing before it is the plain hexagon.
EXEMPTING = (
    HEXAGON + b'\n[[exemptions]]\ncheck = "Stub"\nunit = "src/app/domain/rules.py"\n'
    b'reason = "kept until the rewrite"\n'
)
EARLIER = "a" * 40
REVIEWED_EARLIER = "d" * 40
REVIEWED_NEWEST = "e" * 40
OWNERS = b"# who owns what\n* @someone\n/adherence.toml @owner\n"


def _judged(
    reviews: FakeReviews,
    *,
    codeowners: bytes = OWNERS,
    reviewed_earlier: bytes = HEXAGON,
) -> Report:
    """The change that brings the flaw back, judged with the base's own
    landing (EXEMPTING) and the one before it (HEXAGON) on the history."""
    return judge_with(
        {RULES: FIXED, DECLARATION_PATH: EXEMPTING, "CODEOWNERS": codeowners},
        {RULES: STUBBED, DECLARATION_PATH: EXEMPTING, "CODEOWNERS": codeowners},
        when=WHEN,
        history=(BASE.revision, EARLIER),
        reviews=reviews,
        landed={
            EARLIER: {DECLARATION_PATH: HEXAGON},
            REVIEWED_EARLIER: {DECLARATION_PATH: reviewed_earlier},
            REVIEWED_NEWEST: {DECLARATION_PATH: EXEMPTING},
        },
    )


def _approved_earlier() -> Landing:
    return Landing(author="alice", approvals=(Approval("owner", REVIEWED_EARLIER),))


def _notices(report: Report) -> list[str]:
    return [n.message for n in report.notices]


def _judged_under_the_earlier(report: Report) -> None:
    (finding,) = report.findings
    assert finding.exempt is None, "judged under the unapproved exemption"
    assert finding.provenance is Provenance.INTRODUCED
    assert report.verdict is Verdict.LOWERED


def test_judge_change_after_an_unapproved_landing_is_judged_under_the_approved() -> (
    None
):
    """Given a declaration edit that landed with no approval, after one a code
    owner approved, When the next change is judged, Then it is judged under
    the approved declaration and the unapproved edit is a notice."""
    report = _judged(
        FakeReviews(
            {
                BASE.revision: Landing(author="mallory"),
                EARLIER: _approved_earlier(),
            }
        )
    )

    _judged_under_the_earlier(report)
    assert any(
        BASE.revision[:12] in n and "not in force" in n for n in _notices(report)
    ), _notices(report)


def test_judge_change_after_an_approval_by_no_code_owner_skips_that_landing() -> None:
    """Given the newest declaration edit approved only by a reviewer the
    base's CODEOWNERS does not name for adherence.toml, When the next change
    is judged, Then that edit is not in force and the notice says why."""
    report = _judged(
        FakeReviews(
            {
                BASE.revision: Landing(
                    author="mallory", approvals=(Approval("bob", REVIEWED_NEWEST),)
                ),
                EARLIER: _approved_earlier(),
            }
        )
    )

    _judged_under_the_earlier(report)
    assert any("bob" in n and "code owner" in n for n in _notices(report))


def test_judge_change_after_approve_then_push_skips_that_landing() -> None:
    """Given an owner's approval of a commit whose adherence.toml differs
    from the one that landed, When the next change is judged, Then the
    approval does not count and that landing is not in force."""
    report = _judged(
        FakeReviews(
            {
                BASE.revision: Landing(
                    author="mallory", approvals=(Approval("owner", REVIEWED_EARLIER),)
                ),
                EARLIER: _approved_earlier(),
            }
        )
    )

    _judged_under_the_earlier(report)
    assert any(
        "owner" in n and "differs from the landed one" in n for n in _notices(report)
    ), _notices(report)


def test_judge_change_after_a_landing_with_no_pr_or_unreadable_reviews_skips_it() -> (
    None
):
    """Given the newest declaration edit landed by a direct push, or with
    reviews the code host cannot give, When the next change is judged, Then
    the walk skips it with a notice and the approved edit before it is in
    force."""
    pushed = _judged(
        FakeReviews(
            {BASE.revision: NoLandingPR(BASE.revision), EARLIER: _approved_earlier()}
        )
    )
    unreadable = _judged(
        FakeReviews(
            {
                BASE.revision: ReviewsUnavailable("HTTP 502"),
                EARLIER: _approved_earlier(),
            }
        )
    )

    _judged_under_the_earlier(pushed)
    assert any("no pull request" in n for n in _notices(pushed)), _notices(pushed)
    _judged_under_the_earlier(unreadable)
    assert any("HTTP 502" in n for n in _notices(unreadable))


def test_judge_change_with_no_approved_landing_left_is_judged_undeclared() -> None:
    """Given no landing of adherence.toml that carried a counted approval,
    When the change is judged, Then the repository is judged undeclared: no
    layer check passes, the verdict is inconclusive at best, and a notice
    says why."""
    report = _judged(
        FakeReviews(
            {
                BASE.revision: Landing(author="mallory"),
                EARLIER: NoLandingPR(EARLIER),
            }
        )
    )

    assert report.verdict not in (Verdict.HELD, Verdict.RAISED)
    assert report.findings == ()
    assert any("undeclared" in n for n in _notices(report)), _notices(report)


def test_judge_change_with_a_team_entry_counts_no_owner() -> None:
    """Given CODEOWNERS naming only a team for adherence.toml, When an edit's
    landing is approved by a member of it, Then the approval does not count
    and the team entry is a notice."""
    report = _judged(
        FakeReviews(
            {BASE.revision: Landing(author="mallory"), EARLIER: _approved_earlier()}
        ),
        codeowners=b"adherence.toml @example/owners\n",
    )

    assert report.findings == ()
    assert any("@example/owners" in n and "team" in n for n in _notices(report))


def test_judge_change_where_reviews_are_unknown_keeps_the_landed_declaration() -> None:
    """Given a stage that cannot know who approved a landing (Unknown), When
    the change is judged, Then the landed declaration stands."""
    report = _judged(FakeReviews())

    (finding,) = report.findings
    assert finding.exempt == "kept until the rewrite"
    assert report.verdict is Verdict.HELD


def test_judge_change_after_an_edit_approved_only_by_its_author_refuses_it() -> None:
    """Given a declaration edit approved only by the author of the pull
    request that landed it, a code owner by CODEOWNERS, When the next change
    is judged, Then the edit is not in force and the report says why."""
    report = _judged(
        FakeReviews(
            {
                BASE.revision: Landing(
                    author="Carol", approvals=(Approval("carol", REVIEWED_NEWEST),)
                ),
                EARLIER: _approved_earlier(),
            }
        ),
        codeowners=b"/adherence.toml @owner @carol\n",
    )

    _judged_under_the_earlier(report)
    assert any(
        "carol" in n and "author" in n and "Q11" in n for n in _notices(report)
    ), _notices(report)


def test_judge_change_after_the_owner_approved_their_own_edit_refuses_it() -> None:
    """Given a declaration edit the owner both authored and approved (design
    Q11, still open), When the next change is judged, Then the approval is
    refused until the owner rules, and the report says why."""
    report = _judged(
        FakeReviews(
            {
                BASE.revision: Landing(
                    author="owner", approvals=(Approval("owner", REVIEWED_NEWEST),)
                ),
                EARLIER: _approved_earlier(),
            }
        )
    )

    _judged_under_the_earlier(report)
    assert any("owner" in n and "Q11" in n for n in _notices(report))
