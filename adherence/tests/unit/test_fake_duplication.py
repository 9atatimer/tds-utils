"""The fake DuplicationPort passes the same contract as the jscpd adapter."""

from __future__ import annotations

from adherence.adapters.fakes import FakeDuplication
from adherence.ports.duplication import DuplicationPort
from tests.duplication_contract import SHARED, DuplicationContract


class TestFakeDuplication(DuplicationContract):
    def port(self) -> DuplicationPort:
        return FakeDuplication((SHARED,))
