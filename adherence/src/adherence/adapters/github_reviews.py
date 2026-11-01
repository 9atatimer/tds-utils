"""adapters/github_reviews.py -- ReviewPort over the GitHub REST API.

The `ci` stage's adapter (ARCHITECTURE.ARCH-ADHERENCE.md, Module map and
Where it runs): the pull request that landed a commit, its author, and
the approvals that still stand on it, each with its reviewer and the
commit it reviewed. The standard library speaks HTTP; the composition
root reads the job's GITHUB_TOKEN and repository from the environment and
passes them in, so nothing here reads the environment. An API error, a
body that does not read, or a landing PR that cannot be resolved is the
typed ReviewsUnavailable; the Deadline caps every request and a passed
one is TimedOut.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from typing import cast

from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import (
    Approval,
    Landing,
    NoLandingPR,
    ReviewsUnavailable,
    Unknown,
)
from adherence.domain.target import is_object_id

# --- Constants ---------------------------------------------------------------

API = "https://api.github.com"
API_VERSION = "2022-11-28"
# owner/name, as GITHUB_REPOSITORY names it.
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
PER_PAGE = 100
# Reviews past this many pages are not read; the landing is unavailable.
MAX_PAGES = 10
# The most bytes one response may carry.
MAX_BODY = 8 * 1024 * 1024
# A review in these states says nothing about the reviewer's standing.
SILENT_STATES = frozenset({"COMMENTED", "PENDING"})

Json = object


class _Failed(Exception):
    """The code host could not answer, with the reason."""


class _Expired(Exception):
    """The deadline passed before the answer."""


# --- Predicates --------------------------------------------------------------


def is_merged(pull: Mapping[str, object]) -> bool:
    """Whether a pull request was merged."""
    return pull.get("merged_at") is not None


# --- Pure helpers ------------------------------------------------------------


def _mapping(value: Json, what: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise _Failed(f"{what} is not an object")
    return cast(Mapping[str, object], value)


def _list(value: Json, what: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise _Failed(f"{what} is not a list")
    return value


def _login(value: Json, what: str) -> str:
    login = _mapping(value, what).get("login")
    if not isinstance(login, str) or not login:
        raise _Failed(f"{what} names no login")
    return login


def landing_pull(commit: str, pulls: Sequence[object]) -> Mapping[str, object] | None:
    """The merged pull request that landed the commit: the one whose merge
    commit it is, else the only merged one; None when none merged."""
    merged = [p for p in (_mapping(p, "a pull request") for p in pulls) if is_merged(p)]
    if not merged:
        return None
    exact = [p for p in merged if p.get("merge_commit_sha") == commit]
    if len(exact) == 1:
        return exact[0]
    if len(merged) == 1:
        return merged[0]
    raise _Failed(f"{len(merged)} merged pull requests carry {commit}")


def standing_approvals(reviews: Sequence[object]) -> tuple[Approval, ...]:
    """The approvals that stand: each reviewer's latest review that says
    anything, when it approves, with the commit it reviewed. A comment
    leaves the standing as it was; a later request for changes, or a
    dismissal, withdraws an approval. A review whose user is null (a
    deleted account) has no reviewer to stand for and is skipped."""
    latest: dict[str, tuple[str, object]] = {}
    for review in reviews:
        entry = _mapping(review, "a review")
        state = entry.get("state")
        if not isinstance(state, str) or state in SILENT_STATES:
            continue
        if entry.get("user") is None:
            continue
        latest[_login(entry.get("user"), "a review's user")] = (
            state,
            entry.get("commit_id"),
        )
    return tuple(
        Approval(reviewer, commit)
        for reviewer, (state, commit) in sorted(latest.items())
        if state == "APPROVED" and isinstance(commit, str) and is_object_id(commit)
    )


# --- The adapter -------------------------------------------------------------


class GitHubReviews:
    """ReviewPort over the REST API of one repository, with the job's token.

    `opener` is urllib's; a test passes one that serves recorded responses.
    `clock` is read only to compare it to the Deadline.
    """

    def __init__(
        self,
        *,
        repository: str | None,
        token: str | None,
        api: str = API,
        opener: urllib.request.OpenerDirector | None = None,
        per_page: int = PER_PAGE,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._repository = repository
        self._token = token
        self._api = api.rstrip("/")
        self._opener = opener or urllib.request.build_opener()
        self._per_page = per_page
        self._clock = clock

    def _unready(self, commit: str) -> str | None:
        """Why no request can be made for the commit, or None."""
        if not self._token:
            return "no GITHUB_TOKEN to read the code host's reviews with"
        if not self._repository or not REPOSITORY.fullmatch(self._repository):
            return "no GITHUB_REPOSITORY (owner/name) to read the reviews of"
        if ".." in self._repository:
            return f"{self._repository} is not a repository name"
        if not is_object_id(commit):
            return f"{commit!r} is not a commit's object id"
        return None

    def _remaining(self, deadline: Deadline | None) -> float | None:
        if deadline is None:
            return None
        left = deadline.epoch_seconds - self._clock()
        if left <= 0:
            raise _Expired
        return left

    def _get(self, path: str, deadline: Deadline | None) -> Json:
        """The JSON body of one GET under the repository."""
        request = urllib.request.Request(
            f"{self._api}/repos/{self._repository}/{path}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "X-GitHub-Api-Version": API_VERSION,
                "User-Agent": "adherence-github-reviews",
            },
        )
        timeout = self._remaining(deadline)
        try:
            with self._opener.open(request, timeout=timeout) as response:
                body = response.read(MAX_BODY + 1)
        except urllib.error.HTTPError as error:
            raise _Failed(f"GET {path}: HTTP {error.code}") from error
        except TimeoutError as error:
            raise _Expired from error
        except (urllib.error.URLError, OSError) as error:
            raise _Failed(f"GET {path}: {error}") from error
        if len(body) > MAX_BODY:
            raise _Failed(f"GET {path}: the response is larger than {MAX_BODY} bytes")
        try:
            return cast(Json, json.loads(body))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise _Failed(f"GET {path}: the body is not JSON: {error}") from error

    def _reviews(self, number: int, deadline: Deadline | None) -> list[object]:
        """Every review of the pull request, page by page."""
        found: list[object] = []
        for page in range(1, MAX_PAGES + 1):
            batch = _list(
                self._get(
                    f"pulls/{number}/reviews?per_page={self._per_page}&page={page}",
                    deadline,
                ),
                "the reviews",
            )
            found.extend(batch)
            if len(batch) < self._per_page:
                return found
        raise _Failed(
            f"pull request {number} has more than {MAX_PAGES} pages of reviews"
        )

    def _landing(self, commit: str, deadline: Deadline | None) -> Landing | NoLandingPR:
        pulls = _list(
            self._get(f"commits/{commit}/pulls?per_page={PER_PAGE}", deadline),
            "the pull requests of a commit",
        )
        pull = landing_pull(commit, pulls)
        if pull is None:
            return NoLandingPR(commit)
        number = pull.get("number")
        if not isinstance(number, int) or isinstance(number, bool):
            raise _Failed("the landing pull request has no number")
        author = _login(pull.get("user"), "the landing pull request's user")
        return Landing(author, standing_approvals(self._reviews(number, deadline)))

    def approvals(
        self, commit: str, deadline: Deadline | None
    ) -> Landing | NoLandingPR | Unknown | ReviewsUnavailable | TimedOut:
        unready = self._unready(commit)
        if unready is not None:
            return ReviewsUnavailable(unready)
        try:
            return self._landing(commit, deadline)
        except _Expired:
            return TimedOut(f"read the reviews of the landing of {commit[:12]}")
        except _Failed as failure:
            return ReviewsUnavailable(str(failure))
