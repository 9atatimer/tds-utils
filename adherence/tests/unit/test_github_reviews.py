"""The github_reviews ReviewPort adapter (ARCHITECTURE.ARCH-ADHERENCE.md,
Module map: adapters/github_reviews.py) passes ReviewPort's contract
against recorded REST fixtures, never the live API, in the unit tier."""

from __future__ import annotations

import http.client
import io
import urllib.error
import urllib.request
import urllib.response
from email.message import Message

from adherence.adapters.github_reviews import GitHubReviews, standing_approvals
from adherence.domain.deadline import TimedOut
from adherence.domain.declaration import (
    DECLARATION_PATH,
    Approval,
    DeclarationUnreadable,
    Landing,
    NoLandingPR,
    ReviewsUnavailable,
)
from adherence.ports.review import ReviewPort
from tests.github_fixture import (
    BRANCH,
    RAW,
    REPOSITORY,
    TOKEN,
    FixtureHandler,
    fixture_opener,
)
from tests.review_contract import LANDED, REVIEWED, ReviewContract

PAGED = "5" * 40
AMBIGUOUS = "6" * 40
GARBLED = "7" * 40
OPEN_ONLY = "8" * 40
BRANCHED = "b" * 40
PAGED_PULLS = "c" * 40
# Landed by PR 61, approved on a commit where adherence.toml is absent, on
# one the code host does not know, and on one whose read fails.
CONTENTS = "9" * 40
DELETED_AT = "f" * 40
UNKNOWN_AT = "abcd" * 10
ERRORED_AT = "1234" * 10


def _who(answer: object) -> tuple[str, tuple[Approval, ...]]:
    """A landing's author and standing approvals."""
    assert isinstance(answer, Landing), answer
    return answer.author, answer.approvals


class TestGitHubReviews(ReviewContract):
    def reviews(self) -> ReviewPort:
        opener, _handler = fixture_opener()
        return GitHubReviews(
            branch=BRANCH, repository=REPOSITORY, token=TOKEN, opener=opener
        )


def test_github_reviews_sends_the_token_and_asks_the_rest_api() -> None:
    """Given the job's token, When a landing's approvals are asked for, Then
    every request carries it as a bearer token to the REST API: JSON for
    the listings, the raw media type for adherence.toml at the commit an
    approval reviewed."""
    opener, handler = fixture_opener()

    GitHubReviews(
        branch=BRANCH, repository=REPOSITORY, token=TOKEN, opener=opener
    ).approvals(LANDED, None)

    assert [r.full_url.split("?")[0] for r in handler.requests] == [
        f"https://api.github.com/repos/{REPOSITORY}/commits/{LANDED}/pulls",
        f"https://api.github.com/repos/{REPOSITORY}/pulls/7",
        f"https://api.github.com/repos/{REPOSITORY}/pulls/7/reviews",
        f"https://api.github.com/repos/{REPOSITORY}/contents/{DECLARATION_PATH}",
    ]
    assert handler.requests[-1].full_url.endswith(f"?ref={REVIEWED}")
    for request in handler.requests:
        assert request.get_header("Authorization") == f"Bearer {TOKEN}"
    assert [r.get_header("Accept") for r in handler.requests] == [
        "application/vnd.github+json",
        "application/vnd.github+json",
        "application/vnd.github+json",
        RAW,
    ]


def test_github_reviews_reads_the_merger_from_the_pull_request_itself() -> None:
    """Given landing pull requests whose own object names no merger -- the
    key absent, or null -- When their approvals are asked for, Then the
    merger is None; the listing of a commit's pull requests never names
    one, so the merger is read from the pull request, as for LANDED."""
    opener, _handler = fixture_opener()
    reviews = GitHubReviews(
        branch=BRANCH, repository=REPOSITORY, token=TOKEN, opener=opener
    )

    for commit in (PAGED, BRANCHED):
        answer = reviews.approvals(commit, None)
        assert isinstance(answer, Landing) and answer.merged_by is None, commit


class _PullUnreadableHandler(FixtureHandler):
    """The recorded responses, but the landing pull request's own object
    answers HTTP 502."""

    def https_open(self, request: urllib.request.Request) -> urllib.response.addinfourl:
        if not request.full_url.split("?")[0].endswith("/pulls/7"):
            return super().https_open(request)
        response = urllib.response.addinfourl(
            io.BytesIO(b'{"message": "error"}'), Message(), request.full_url, 502
        )
        response.msg = "Error"
        return response


def test_github_reviews_whose_landing_pull_request_cannot_be_read_are_unavailable() -> (
    None
):
    """Given a landing pull request whose own object the code host cannot
    give, When its approvals are asked for, Then the answer is the typed
    unavailable failure: who merged it is not known."""
    opener = urllib.request.build_opener(_PullUnreadableHandler())
    reviews = GitHubReviews(
        branch=BRANCH, repository=REPOSITORY, token=TOKEN, opener=opener
    )

    answer = reviews.approvals(LANDED, None)

    assert isinstance(answer, ReviewsUnavailable) and "502" in answer.reason, answer


def test_github_reviews_reads_every_page_of_reviews() -> None:
    """Given a PR whose reviews span two pages, When its approvals are asked
    for, Then the approval on the second page stands."""
    opener, _handler = fixture_opener()
    reviews = GitHubReviews(
        branch=BRANCH, repository=REPOSITORY, token=TOKEN, opener=opener, per_page=2
    )

    assert _who(reviews.approvals(PAGED, None)) == (
        "alice",
        (Approval("owner", PAGED),),
    )


def test_github_reviews_with_no_merged_pr_is_no_landing() -> None:
    """Given a commit only an open pull request carries, When its approvals
    are asked for, Then no PR landed it."""
    opener, _handler = fixture_opener()
    reviews = GitHubReviews(
        branch=BRANCH, repository=REPOSITORY, token=TOKEN, opener=opener
    )

    assert reviews.approvals(OPEN_ONLY, None) == NoLandingPR(OPEN_ONLY)


def test_github_reviews_that_cannot_resolve_the_landing_are_unavailable() -> None:
    """Given two merged PRs carrying the commit, neither landing it as its
    merge commit, or a body that is not JSON, When approvals are asked for,
    Then the answer is the typed unavailable failure."""
    opener, _handler = fixture_opener()
    reviews = GitHubReviews(
        branch=BRANCH, repository=REPOSITORY, token=TOKEN, opener=opener
    )

    for commit in (AMBIGUOUS, GARBLED):
        assert isinstance(reviews.approvals(commit, None), ReviewsUnavailable), commit


def test_github_reviews_without_a_token_or_a_commit_id_asks_nothing() -> None:
    """Given no token, no repository, no branch, or a commit that is not an
    object id,
    When approvals are asked for, Then the answer is unavailable naming why,
    and no request is made."""
    opener, handler = fixture_opener()

    for reviews, commit in (
        (
            GitHubReviews(
                branch=BRANCH, repository=REPOSITORY, token=None, opener=opener
            ),
            LANDED,
        ),
        (
            GitHubReviews(branch=BRANCH, repository=None, token=TOKEN, opener=opener),
            LANDED,
        ),
        (
            GitHubReviews(
                branch=BRANCH, repository=REPOSITORY, token=TOKEN, opener=opener
            ),
            "HEAD~1",
        ),
        (
            GitHubReviews(
                branch=BRANCH, repository="a/b/../c", token=TOKEN, opener=opener
            ),
            LANDED,
        ),
        (
            GitHubReviews(
                branch=None, repository=REPOSITORY, token=TOKEN, opener=opener
            ),
            LANDED,
        ),
    ):
        answer = reviews.approvals(commit, None)
        assert isinstance(answer, ReviewsUnavailable) and answer.reason, commit

    assert handler.requests == []


def test_a_review_by_a_deleted_account_is_skipped_not_fatal() -> None:
    """Given a review whose user is null (a deleted account, as GitHub gives
    it) beside an owner's approval, When the standing approvals are read,
    Then the null-user review is skipped and the owner's approval stands."""
    reviews = [
        {"user": None, "state": "APPROVED", "commit_id": LANDED},
        {"user": {"login": "owner"}, "state": "APPROVED", "commit_id": LANDED},
    ]

    assert standing_approvals(reviews) == (Approval("owner", LANDED),)


class _Truncated(io.BytesIO):
    """A body the connection cut short."""

    def read(self, size: int | None = -1) -> bytes:
        raise http.client.IncompleteRead(b"[", 10)


class _TruncatingHandler(urllib.request.BaseHandler):
    handler_order = 100

    def https_open(self, request: urllib.request.Request) -> urllib.response.addinfourl:
        response = urllib.response.addinfourl(
            _Truncated(), Message(), request.full_url, 200
        )
        response.msg = "OK"
        return response


def test_github_reviews_with_a_truncated_body_are_unavailable() -> None:
    """Given a response whose body the connection cuts short, When approvals
    are asked for, Then the answer is the typed unavailable failure, not a
    crash."""
    opener = urllib.request.build_opener(_TruncatingHandler())
    reviews = GitHubReviews(
        branch=BRANCH, repository=REPOSITORY, token=TOKEN, opener=opener
    )

    answer = reviews.approvals(LANDED, None)

    assert isinstance(answer, ReviewsUnavailable) and answer.reason


def test_github_reviews_finds_the_pr_that_landed_on_the_judged_branch() -> None:
    """Given a commit two merged PRs carry, one into another branch, neither
    with it as its merge commit, When its approvals are asked for on the
    judged branch, Then the landing is the PR into that branch."""
    opener, _handler = fixture_opener()
    reviews = GitHubReviews(
        branch=BRANCH, repository=REPOSITORY, token=TOKEN, opener=opener
    )

    assert _who(reviews.approvals(BRANCHED, None)) == (
        "alice",
        (Approval("owner", BRANCHED),),
    )


def test_github_reviews_reads_every_page_of_a_commits_pull_requests() -> None:
    """Given a commit whose pull requests span two pages, the one that landed
    it on the judged branch on the second, When its approvals are asked
    for, Then that PR is the landing."""
    opener, _handler = fixture_opener()
    reviews = GitHubReviews(
        branch=BRANCH, repository=REPOSITORY, token=TOKEN, opener=opener, per_page=2
    )

    assert _who(reviews.approvals(PAGED_PULLS, None)) == (
        "alice",
        (Approval("owner", PAGED_PULLS),),
    )


def test_github_reviews_tells_an_absent_declaration_from_an_unreadable_one() -> None:
    """Given approvals of a commit where adherence.toml is absent, of one the
    code host does not know, and of one whose read fails, When the landing's
    approvals are asked for, Then the first reads as absent, the others as
    unreadable with the reason, and the landing still stands."""
    opener, _handler = fixture_opener()
    reviews = GitHubReviews(
        branch=BRANCH, repository=REPOSITORY, token=TOKEN, opener=opener
    )

    answer = reviews.approvals(CONTENTS, None)

    assert isinstance(answer, Landing)
    texts = dict(answer.reviewed)
    assert texts[DELETED_AT] is None
    for commit in (UNKNOWN_AT, ERRORED_AT):
        text = texts[commit]
        assert isinstance(text, DeclarationUnreadable) and text.reason, commit


class _ShortBodyHandler(urllib.request.BaseHandler):
    """Every response promises more bytes than it carries, and the read
    returns the short body without raising, as http.client's read(amt)
    does when the connection closes early."""

    handler_order = 100

    def https_open(self, request: urllib.request.Request) -> urllib.response.addinfourl:
        headers = Message()
        headers["Content-Type"] = "application/json"
        headers["Content-Length"] = "100"
        response = urllib.response.addinfourl(
            io.BytesIO(b"[]"), headers, request.full_url, 200
        )
        response.msg = "OK"
        return response


def test_github_reviews_with_a_body_shorter_than_its_length_are_unavailable() -> None:
    """Given a response whose body ends before its Content-Length, with no
    error raised, When approvals are asked for, Then the answer is the typed
    unavailable failure, not the short body read as the answer."""
    opener = urllib.request.build_opener(_ShortBodyHandler())
    reviews = GitHubReviews(
        branch=BRANCH, repository=REPOSITORY, token=TOKEN, opener=opener
    )

    answer = reviews.approvals(LANDED, None)

    assert isinstance(answer, ReviewsUnavailable) and "100" in answer.reason, answer


class _ConnectTimeoutHandler(urllib.request.BaseHandler):
    """Every request times out on connect, as urllib reports it: a URLError
    whose reason is the TimeoutError."""

    handler_order = 100

    def https_open(self, request: urllib.request.Request) -> urllib.response.addinfourl:
        raise urllib.error.URLError(TimeoutError("timed out"))


def test_github_reviews_whose_connect_times_out_are_timed_out() -> None:
    """Given a request whose connect times out, When approvals are asked
    for, Then the answer is TimedOut, not unavailable."""
    opener = urllib.request.build_opener(_ConnectTimeoutHandler())
    reviews = GitHubReviews(
        branch=BRANCH, repository=REPOSITORY, token=TOKEN, opener=opener
    )

    assert isinstance(reviews.approvals(LANDED, None), TimedOut)


class _ShortRawHandler(FixtureHandler):
    """The recorded responses, but adherence.toml's bytes end before the
    Content-Length the response carries."""

    def https_open(self, request: urllib.request.Request) -> urllib.response.addinfourl:
        response = super().https_open(request)
        if request.get_header("Accept") != RAW:
            return response
        whole = response.read()
        headers = Message()
        headers["Content-Length"] = str(len(whole) + 1)
        short = urllib.response.addinfourl(
            io.BytesIO(whole), headers, request.full_url, 200
        )
        short.msg = "OK"
        return short


def test_github_reviews_with_a_short_reviewed_declaration_say_it_cannot_be_read() -> (
    None
):
    """Given adherence.toml at the reviewed commit whose bytes end before
    their Content-Length, When the landing's approvals are asked for, Then
    that commit's declaration is unreadable, never the short bytes."""
    opener = urllib.request.build_opener(_ShortRawHandler())
    reviews = GitHubReviews(
        branch=BRANCH, repository=REPOSITORY, token=TOKEN, opener=opener
    )

    answer = reviews.approvals(LANDED, None)

    assert isinstance(answer, Landing), answer
    assert isinstance(dict(answer.reviewed)[REVIEWED], DeclarationUnreadable), answer
