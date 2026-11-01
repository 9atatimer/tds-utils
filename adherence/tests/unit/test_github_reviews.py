"""The github_reviews ReviewPort adapter (ARCHITECTURE.ARCH-ADHERENCE.md,
Module map: adapters/github_reviews.py) passes ReviewPort's contract
against recorded REST fixtures, never the live API, in the unit tier."""

from __future__ import annotations

import http.client
import io
import urllib.request
import urllib.response
from email.message import Message

from adherence.adapters.github_reviews import GitHubReviews, standing_approvals

from adherence.domain.declaration import (
    Approval,
    Landing,
    NoLandingPR,
    ReviewsUnavailable,
)
from adherence.ports.review import ReviewPort
from tests.github_fixture import BRANCH, REPOSITORY, TOKEN, fixture_opener
from tests.review_contract import LANDED, ReviewContract

PAGED = "5" * 40
AMBIGUOUS = "6" * 40
GARBLED = "7" * 40
OPEN_ONLY = "8" * 40
BRANCHED = "b" * 40
PAGED_PULLS = "c" * 40


class TestGitHubReviews(ReviewContract):
    def reviews(self) -> ReviewPort:
        opener, _handler = fixture_opener()
        return GitHubReviews(
            branch=BRANCH, repository=REPOSITORY, token=TOKEN, opener=opener
        )


def test_github_reviews_sends_the_token_and_asks_the_rest_api() -> None:
    """Given the job's token, When a landing's approvals are asked for, Then
    every request carries it as a bearer token to the REST API's JSON."""
    opener, handler = fixture_opener()

    GitHubReviews(
        branch=BRANCH, repository=REPOSITORY, token=TOKEN, opener=opener
    ).approvals(LANDED, None)

    assert [r.full_url.split("?")[0] for r in handler.requests] == [
        f"https://api.github.com/repos/{REPOSITORY}/commits/{LANDED}/pulls",
        f"https://api.github.com/repos/{REPOSITORY}/pulls/7/reviews",
    ]
    for request in handler.requests:
        assert request.get_header("Authorization") == f"Bearer {TOKEN}"
        assert request.get_header("Accept") == "application/vnd.github+json"


def test_github_reviews_reads_every_page_of_reviews() -> None:
    """Given a PR whose reviews span two pages, When its approvals are asked
    for, Then the approval on the second page stands."""
    opener, _handler = fixture_opener()
    reviews = GitHubReviews(
        branch=BRANCH, repository=REPOSITORY, token=TOKEN, opener=opener, per_page=2
    )

    assert reviews.approvals(PAGED, None) == Landing(
        author="alice", approvals=(Approval("owner", PAGED),)
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

    assert reviews.approvals(BRANCHED, None) == Landing(
        author="alice", approvals=(Approval("owner", BRANCHED),)
    )


def test_github_reviews_reads_every_page_of_a_commits_pull_requests() -> None:
    """Given a commit whose pull requests span two pages, the one that landed
    it on the judged branch on the second, When its approvals are asked
    for, Then that PR is the landing."""
    opener, _handler = fixture_opener()
    reviews = GitHubReviews(
        branch=BRANCH, repository=REPOSITORY, token=TOKEN, opener=opener, per_page=2
    )

    assert reviews.approvals(PAGED_PULLS, None) == Landing(
        author="alice", approvals=(Approval("owner", PAGED_PULLS),)
    )
