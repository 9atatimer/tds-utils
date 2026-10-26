"""Approval counting in domain/declaration (ARCHITECTURE.ARCH-ADHERENCE.md,
Module map: approval counting over the base's CODEOWNERS entries and the
approvals passed in as values). Values in, values out; no fake."""

from __future__ import annotations

from adherence.domain.declaration import (
    Approval,
    DeclarationUnreadable,
    LandedRevision,
    Landing,
    NoLandingPR,
    ReviewsUnavailable,
    Unknown,
    counted_landing,
    parse_codeowners,
)

COMMIT = "1" * 40
REVIEWED = "2" * 40
TEXT = b"[layers]\n"
OWNERS = parse_codeowners(b"/adherence.toml @Owner\n")


def _landing(*approvals: Approval, author: str = "alice") -> LandedRevision:
    return LandedRevision(
        COMMIT,
        Landing(author=author, approvals=approvals),
        text=TEXT,
        reviewed=((REVIEWED, TEXT),),
    )


def test_codeowners_last_matching_entry_names_the_owners() -> None:
    """Given CODEOWNERS whose later entry also matches adherence.toml, When
    its owners are asked for, Then the last matching entry wins, as GitHub
    reads it, and comments are not owners."""
    owners = parse_codeowners(
        b"# comment\n*  @everyone   # trailing\n*.toml @tomls\n/docs/ @writers\n"
    )

    assert owners.owners_of("adherence.toml") == ("@tomls",)
    assert owners.owners_of("docs/a.md") == ("@writers",)
    assert parse_codeowners(b"").owners_of("adherence.toml") == ()


def test_codeowners_patterns_match_as_gitignore_does() -> None:
    """Given unanchored, anchored and directory patterns, When adherence.toml
    at the root is matched, Then only the patterns that name it match."""
    for pattern, hit in (
        ("adherence.toml", True),
        ("/adherence.toml", True),
        ("**/adherence.toml", True),
        ("*", True),
        ("sub/adherence.toml", False),
        ("docs/", False),
        ("/adherence", False),
    ):
        owners = parse_codeowners(f"{pattern} @x\n".encode())
        assert (owners.owners_of("adherence.toml") == ("@x",)) is hit, pattern


def test_an_owners_approval_of_the_landed_bytes_counts() -> None:
    """Given an approval by a code owner (any letter case) of a commit whose
    adherence.toml equals the landed one, When the landing is counted, Then
    it is in force."""
    assert counted_landing(_landing(Approval("owner", REVIEWED)), OWNERS).in_force


def test_an_approval_of_other_or_unreadable_bytes_does_not_count() -> None:
    """Given an owner's approval of a commit whose adherence.toml differs, is
    absent, or cannot be read, When the landing is counted, Then it is not
    in force."""
    for reviewed in (b"[layers]\n# pushed after\n", None, DeclarationUnreadable("x")):
        revision = LandedRevision(
            COMMIT,
            Landing(author="alice", approvals=(Approval("owner", REVIEWED),)),
            text=TEXT,
            reviewed=((REVIEWED, reviewed),),
        )
        assert not counted_landing(revision, OWNERS).in_force, reviewed


def test_an_unreadable_landed_declaration_counts_no_approval() -> None:
    """Given a landing whose own adherence.toml cannot be read, When an owner's
    approval of it is counted, Then nothing compares equal to it."""
    revision = LandedRevision(
        COMMIT,
        Landing(author="alice", approvals=(Approval("owner", REVIEWED),)),
        text=DeclarationUnreadable("refused"),
        reviewed=((REVIEWED, DeclarationUnreadable("refused")),),
    )

    assert not counted_landing(revision, OWNERS).in_force


def test_an_approved_deletion_counts() -> None:
    """Given an owner's approval of a commit where adherence.toml is absent,
    on a landing that deleted it, When the landing is counted, Then it is in
    force."""
    revision = LandedRevision(
        COMMIT,
        Landing(author="alice", approvals=(Approval("owner", REVIEWED),)),
        text=None,
        reviewed=((REVIEWED, None),),
    )

    assert counted_landing(revision, OWNERS).in_force


def test_each_answer_but_a_counted_landing_or_unknown_is_skipped() -> None:
    """Given each of ReviewPort's answers, When the landing is counted, Then
    only Unknown and a landing with a counted approval are in force, and
    every skip carries a notice."""
    assert counted_landing(LandedRevision(COMMIT, Unknown("laptop")), OWNERS).in_force
    for answer in (
        NoLandingPR(COMMIT),
        ReviewsUnavailable("HTTP 500"),
        Landing(author="alice"),
    ):
        counting = counted_landing(LandedRevision(COMMIT, answer), OWNERS)
        assert not counting.in_force and counting.notices, answer


def test_a_team_or_email_entry_counts_as_no_owner_and_is_a_notice() -> None:
    """Given CODEOWNERS naming a team and an email for adherence.toml, When an
    approval is counted, Then neither names an owner and each is a notice."""
    owners = parse_codeowners(b"adherence.toml @org/team someone@example.com\n")

    counting = counted_landing(_landing(Approval("team-member", REVIEWED)), owners)

    assert not counting.in_force
    notices = " ".join(n.message for n in counting.notices)
    assert "@org/team" in notices and "someone@example.com" in notices
