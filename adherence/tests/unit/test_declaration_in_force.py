"""The declaration in force (DESIGN.ARCH-ADHERENCE.md, Behaviors: An
unapproved declaration is not in force; ARCHITECTURE.ARCH-ADHERENCE.md,
Use-case surface), driven through judge_change by its signature: the
newest landed revision of adherence.toml whose landing a code owner
approved, on a commit whose declaration equals the landed one."""

from __future__ import annotations

from adherence.adapters.fakes import FakeReviews
from adherence.domain.deadline import TimedOut
from adherence.domain.declaration import (
    DECLARATION_PATH,
    Approval,
    DeclarationUnreadable,
    Landing,
    NoLandingPR,
    ReviewsUnavailable,
)
from adherence.domain.finding import Provenance
from adherence.domain.report import Report, Verdict
from adherence.domain.target import Base, Head
from adherence.ports.repository import Refused
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
    codeowners: bytes | Refused | TimedOut = OWNERS,
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


TEAM = b"adherence.toml @example/owners\n"


def test_judge_change_with_a_team_entry_counts_no_owner() -> None:
    """Given CODEOWNERS naming only a team for adherence.toml, When the
    newest edit's landing is approved, on the landed bytes, by a login that
    is a member of the team, Then the approval does not count -- the engine
    cannot resolve a team's members -- and the team entry is a notice."""
    report = _judged(
        FakeReviews(
            {
                BASE.revision: Landing(
                    author="mallory",
                    approvals=(Approval("team-member", REVIEWED_NEWEST),),
                ),
                EARLIER: NoLandingPR(EARLIER),
            }
        ),
        codeowners=TEAM,
    )

    assert report.findings == (), "the team member's approval was counted"
    assert any(
        "team-member" in n and "not a code owner" in n for n in _notices(report)
    ), _notices(report)
    assert any("@example/owners" in n and "team" in n for n in _notices(report))


def test_judge_change_says_a_team_entry_counts_no_owner_once_per_run() -> None:
    """Given CODEOWNERS naming only a team for adherence.toml, When two
    landings of it are walked, Then the team entry is one notice, since it
    is about the file and not about either landing."""
    report = _judged(
        FakeReviews(
            {
                BASE.revision: Landing(author="mallory"),
                EARLIER: _approved_earlier(),
            }
        ),
        codeowners=TEAM,
    )

    assert [n for n in _notices(report) if "@example/owners" in n] == [
        f"CODEOWNERS entry @example/owners for {DECLARATION_PATH} counts as no "
        "owner: only a user (@login) is an owner, never a team or an email"
    ], _notices(report)


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
        "carol" in n and "author" in n and "cannot approve" in n
        for n in _notices(report)
    ), _notices(report)


def test_judge_change_after_the_owner_approved_their_own_edit_refuses_it() -> None:
    """Given a declaration edit the owner both authored and approved, merged
    by no code owner (the merge bot), When the next change is judged, Then
    the approval is refused, since an author cannot approve their own edit,
    and the report says why."""
    report = _judged(
        FakeReviews(
            {
                BASE.revision: Landing(
                    author="owner",
                    approvals=(Approval("owner", REVIEWED_NEWEST),),
                    merged_by="tedium-bot",
                ),
                EARLIER: _approved_earlier(),
            }
        )
    )

    _judged_under_the_earlier(report)
    assert any("owner" in n and "cannot approve" in n for n in _notices(report))


def test_judge_change_after_the_owner_merged_their_own_edit_is_under_it() -> None:
    """Given a declaration edit the owner authored and merged themselves, with
    no approval (design Q11: the one-human repository), When the next change
    is judged, Then that edit is in force and the report names the merge as
    what counted."""
    report = _judged(
        FakeReviews(
            {
                BASE.revision: Landing(author="owner", merged_by="owner"),
                EARLIER: _approved_earlier(),
            }
        )
    )

    (finding,) = report.findings
    assert finding.exempt == "kept until the rewrite", _notices(report)
    assert report.verdict is Verdict.HELD
    assert any(
        BASE.revision[:12] in n and "merged by code owner owner" in n
        for n in _notices(report)
    ), _notices(report)


def test_judge_change_after_an_edit_its_author_alone_merged_skips_it() -> None:
    """Given a declaration edit with no approval that its author, no code
    owner, merged themselves, When the next change is judged, Then the edit
    is not in force: a landing attributable to its author alone counts
    nothing."""
    report = _judged(
        FakeReviews(
            {
                BASE.revision: Landing(author="mallory", merged_by="mallory"),
                EARLIER: _approved_earlier(),
            }
        )
    )

    _judged_under_the_earlier(report)
    assert any(
        BASE.revision[:12] in n and "not in force" in n for n in _notices(report)
    ), _notices(report)
    assert any(
        "approved by owner" in n and EARLIER[:12] in n for n in _notices(report)
    ), _notices(report)


def test_judge_change_whose_own_declaration_is_unreadable_notices_it() -> None:
    """Given a readable declaration in force -- the approved landing, behind
    an unapproved one -- and a change whose own declaration cannot be read,
    When the change is judged, Then it is judged under the declaration in
    force and the unreadable edit is a notice."""
    report = judge_with(
        {RULES: FIXED, DECLARATION_PATH: EXEMPTING, "CODEOWNERS": OWNERS},
        {RULES: STUBBED, DECLARATION_PATH: b"[layers\n", "CODEOWNERS": OWNERS},
        when=WHEN,
        history=(BASE.revision, EARLIER),
        reviews=FakeReviews(
            {BASE.revision: Landing(author="mallory"), EARLIER: _approved_earlier()}
        ),
        landed={
            EARLIER: {DECLARATION_PATH: HEXAGON},
            REVIEWED_EARLIER: {DECLARATION_PATH: HEXAGON},
        },
    )

    _judged_under_the_earlier(report)
    assert any(
        "own declaration cannot be read" in n and "declaration in force" in n
        for n in _notices(report)
    ), _notices(report)


def test_judge_change_whose_walk_cannot_be_made_is_judged_undeclared() -> None:
    """Given a history of adherence.toml that cannot be listed, or reviews
    that time out, When the change is judged, Then the repository is judged
    undeclared and the verdict is inconclusive at best, naming why."""
    for history, reviews in (
        (Refused(DECLARATION_PATH, "shallow clone"), FakeReviews()),
        (TimedOut("list the history"), FakeReviews()),
        ((BASE.revision, EARLIER), FakeReviews({BASE.revision: TimedOut("reviews")})),
    ):
        report = judge_with(
            {RULES: FIXED, DECLARATION_PATH: EXEMPTING},
            {RULES: STUBBED, DECLARATION_PATH: EXEMPTING},
            when=WHEN,
            history=history,
            reviews=reviews,
        )

        assert report.verdict is Verdict.INCONCLUSIVE, history
        assert report.findings == (), history
        assert any("undeclared" in n for n in _notices(report)), history


def test_judge_change_reads_the_codeowners_github_reads_first() -> None:
    """Given CODEOWNERS under .github/ naming no one for adherence.toml and a
    root CODEOWNERS naming the approver, When the landing is counted, Then
    the .github/ one is read, as GitHub reads it, and the approval does not
    count; with no CODEOWNERS anywhere, no approval counts."""
    reviews = FakeReviews({BASE.revision: _approved_earlier()})
    for extra in ({".github/CODEOWNERS": b"*.py @someone\n"}, {}):
        files = {RULES: FIXED, DECLARATION_PATH: HEXAGON, **extra}
        report = judge_with(
            {**files, "CODEOWNERS": OWNERS} if extra else files,
            {**files, RULES: STUBBED},
            when=WHEN,
            reviews=reviews,
            landed={REVIEWED_EARLIER: {DECLARATION_PATH: HEXAGON}},
        )

        assert report.verdict is Verdict.INCONCLUSIVE, extra
        assert any("code owner" in n for n in _notices(report)), extra


def test_judge_change_under_an_unreadable_approved_declaration_is_not_run() -> None:
    """Given the approved landing's adherence.toml does not parse, When the
    change is judged, Then the verdict is not run, as for any declaration in
    force that cannot be read."""
    broken = b"[layers\n"
    report = judge_with(
        {RULES: FIXED, DECLARATION_PATH: broken, "CODEOWNERS": OWNERS},
        {RULES: STUBBED, DECLARATION_PATH: broken, "CODEOWNERS": OWNERS},
        when=WHEN,
        reviews=FakeReviews(
            {
                BASE.revision: Landing(
                    author="alice", approvals=(Approval("owner", REVIEWED_NEWEST),)
                )
            }
        ),
        landed={REVIEWED_NEWEST: {DECLARATION_PATH: broken}},
    )

    assert report.verdict is Verdict.NOT_RUN


def _squashed(reviewed: bytes | DeclarationUnreadable) -> Report:
    """The newest edit approved by an owner on a PR head the checkout cannot
    read (a squash landing), adherence.toml there as the code host gives it."""
    return judge_with(
        {RULES: FIXED, DECLARATION_PATH: EXEMPTING, "CODEOWNERS": OWNERS},
        {RULES: STUBBED, DECLARATION_PATH: EXEMPTING, "CODEOWNERS": OWNERS},
        when=WHEN,
        history=(BASE.revision, EARLIER),
        reviews=FakeReviews(
            {
                BASE.revision: Landing(
                    author="mallory",
                    approvals=(Approval("owner", REVIEWED_NEWEST),),
                    reviewed=((REVIEWED_NEWEST, reviewed),),
                ),
                EARLIER: _approved_earlier(),
            }
        ),
        landed={
            EARLIER: {DECLARATION_PATH: HEXAGON},
            REVIEWED_EARLIER: {DECLARATION_PATH: HEXAGON},
            REVIEWED_NEWEST: {
                DECLARATION_PATH: Refused(DECLARATION_PATH, "bad object")
            },
        },
    )


def test_judge_change_after_a_squash_landing_reads_the_reviewed_declaration() -> None:
    """Given an owner's approval of a PR head no checkout can fetch, whose
    adherence.toml the code host gives equal to the landed one, When the
    next change is judged, Then that landing is in force."""
    report = _squashed(EXEMPTING)

    (finding,) = report.findings
    assert finding.exempt == "kept until the rewrite", _notices(report)
    assert report.verdict is Verdict.HELD


def test_judge_change_with_a_reviewed_declaration_unread_says_so() -> None:
    """Given an owner's approval of a commit whose adherence.toml neither the
    code host nor the checkout can read, When the next change is judged,
    Then the landing is skipped and the notice says the read failed, never
    that the bytes differ."""
    report = _squashed(DeclarationUnreadable("HTTP 502"))

    _judged_under_the_earlier(report)
    assert any("cannot be read" in n and "HTTP 502" in n for n in _notices(report)), (
        _notices(report)
    )
    assert not any("differs" in n for n in _notices(report)), _notices(report)


def test_judge_change_with_codeowners_refused_names_the_file_and_reason() -> None:
    """Given a CODEOWNERS the repository will not hand over, When a landing is
    counted, Then no approval counts and a notice names the file and why,
    rather than the walk reading it as a file that names no one."""
    report = _judged(
        FakeReviews({BASE.revision: _approved_earlier(), EARLIER: _approved_earlier()}),
        codeowners=Refused("CODEOWNERS", "bad object"),
    )

    assert report.findings == ()
    assert any(
        "CODEOWNERS" in n and "cannot be read" in n and "bad object" in n
        for n in _notices(report)
    ), _notices(report)


OLDER = "0" * 40


def _walk_ended(
    report: Report, reviews: FakeReviews, *, first: str = BASE.revision
) -> None:
    """The walk ended at its first landing: judged undeclared with coverage,
    naming the timeout, and the code host never asked about a later one."""
    assert report.verdict is Verdict.INCONCLUSIVE
    assert report.findings == ()
    assert any("timed out" in n and "undeclared" in n for n in _notices(report)), (
        _notices(report)
    )
    assert any(c.path == DECLARATION_PATH for c in report.coverage), report.coverage
    assert reviews.asked == [first], reviews.asked


def _read_at(reads: list[tuple[str, Base | Head]]) -> set[Base | Head]:
    return {at for _path, at in reads}


def _newest_approved_then_earlier() -> FakeReviews:
    """The base landed by mallory with the owner's approval of the newest
    reviewed commit, and the earlier landing approved."""
    return FakeReviews(
        {
            BASE.revision: Landing(
                author="mallory", approvals=(Approval("owner", REVIEWED_NEWEST),)
            ),
            EARLIER: _approved_earlier(),
        }
    )


def test_judge_change_whose_codeowners_read_times_out_ends_the_walk() -> None:
    """Given a CODEOWNERS read that times out, When the newest landing is
    counted, Then the walk ends there: the repository is judged undeclared
    with coverage, and no further landing or reviewed commit is read."""
    reviews = _newest_approved_then_earlier()
    reads: list[tuple[str, Base | Head]] = []

    report = judge_with(
        {RULES: FIXED, DECLARATION_PATH: EXEMPTING, "CODEOWNERS": TimedOut("read")},
        {RULES: STUBBED, DECLARATION_PATH: EXEMPTING},
        when=WHEN,
        history=(BASE.revision, EARLIER),
        reviews=reviews,
        landed={REVIEWED_NEWEST: {DECLARATION_PATH: EXEMPTING}},
        reads=reads,
    )

    _walk_ended(report, reviews)
    assert Base(REVIEWED_NEWEST) not in _read_at(reads), reads


def test_judge_change_whose_reviewed_declaration_read_times_out_ends_the_walk() -> None:
    """Given an owner's approval of a commit the code host gives no
    adherence.toml for, whose read from the repository times out, When that
    landing is counted, Then the walk ends there: the repository is judged
    undeclared with coverage, and the landing before it is never read."""
    reviews = _newest_approved_then_earlier()
    reads: list[tuple[str, Base | Head]] = []

    report = judge_with(
        {RULES: FIXED, DECLARATION_PATH: EXEMPTING, "CODEOWNERS": OWNERS},
        {RULES: STUBBED, DECLARATION_PATH: EXEMPTING, "CODEOWNERS": OWNERS},
        when=WHEN,
        history=(BASE.revision, EARLIER),
        reviews=reviews,
        landed={
            REVIEWED_NEWEST: {DECLARATION_PATH: TimedOut("read")},
            EARLIER: {DECLARATION_PATH: HEXAGON},
            REVIEWED_EARLIER: {DECLARATION_PATH: HEXAGON},
        },
        reads=reads,
    )

    _walk_ended(report, reviews)
    assert not {Base(EARLIER), Base(REVIEWED_EARLIER)} & _read_at(reads), reads


def test_judge_change_whose_landed_declaration_read_times_out_ends_the_walk() -> None:
    """Given the newest landing's own adherence.toml read times out, When
    that landing is counted, Then the walk ends there: the repository is
    judged undeclared with coverage, and neither the commit its approval
    reviewed nor the landing before it is read."""
    reviews = FakeReviews({EARLIER: _approved_earlier(), OLDER: _approved_earlier()})
    reads: list[tuple[str, Base | Head]] = []

    report = judge_with(
        {RULES: FIXED, DECLARATION_PATH: EXEMPTING, "CODEOWNERS": OWNERS},
        {RULES: STUBBED, DECLARATION_PATH: EXEMPTING, "CODEOWNERS": OWNERS},
        when=WHEN,
        history=(EARLIER, OLDER),
        reviews=reviews,
        landed={
            EARLIER: {DECLARATION_PATH: TimedOut("read")},
            REVIEWED_EARLIER: {DECLARATION_PATH: HEXAGON},
            OLDER: {DECLARATION_PATH: HEXAGON},
        },
        reads=reads,
    )

    _walk_ended(report, reviews, first=EARLIER)
    assert not {Base(REVIEWED_EARLIER), Base(OLDER)} & _read_at(reads), reads
