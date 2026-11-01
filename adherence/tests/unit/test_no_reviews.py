"""The no_reviews ReviewPort adapter (ARCHITECTURE.ARCH-ADHERENCE.md, Module
map: adapters/no_reviews.py): a stage that reads no code host answers every
commit Unknown, under which the landed declaration stands."""

from __future__ import annotations

from adherence.adapters.no_reviews import NoReviews
from adherence.domain.declaration import Unknown
from adherence.ports.review import ReviewPort


def test_approvals_without_a_code_host_are_unknown() -> None:
    """Given the no_reviews adapter, When any commit's approvals are asked
    for, Then the answer is Unknown with a reason, never a landing."""
    reviews: ReviewPort = NoReviews()

    answer = reviews.approvals("a" * 40, None)

    assert isinstance(answer, Unknown)
    assert answer.reason
