"""The fake ReviewPort passes the same contract as every code host's."""

from __future__ import annotations

from adherence.adapters.fakes import FakeReviews
from adherence.ports.review import ReviewPort
from tests.review_contract import ReviewContract


class TestFakeReviews(ReviewContract):
    def port(self) -> ReviewPort:
        return FakeReviews()
