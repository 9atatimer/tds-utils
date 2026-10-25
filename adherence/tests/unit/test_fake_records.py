"""The fake RecordsPort passes the same contract as the markdown adapter."""

from __future__ import annotations

from adherence.adapters.fakes import FakeRecords
from adherence.domain.records import Behavior, DesignRecords
from adherence.ports.records import RecordsPort
from tests.records_contract import BEHAVIORS, DESIGN, NOW, RecordsContract


class TestFakeRecords(RecordsContract):
    def port(self) -> RecordsPort:
        return FakeRecords(
            {
                at: DesignRecords(
                    behaviors=tuple(
                        Behavior(name, "Given x, When y, Then z", DESIGN, line)
                        for line, name in enumerate(names, start=1)
                    )
                )
                for at, names in BEHAVIORS.items()
            },
            now=NOW,
        )
