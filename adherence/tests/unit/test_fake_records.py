"""The fake RecordsPort passes the same contract as the markdown adapter."""

from __future__ import annotations

from adherence.adapters.fakes import FakeRecords
from adherence.domain.records import Behavior, DesignRecords, Radar, RadarEntry
from adherence.ports.records import RecordsPort
from tests.records_contract import (
    BEHAVIORS,
    DESIGN,
    NOW,
    RADAR,
    RADARS,
    RecordsContract,
)


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
            radar={
                at: Radar(
                    tuple(
                        RadarEntry(name, ring, RADAR, line)
                        for line, (name, ring) in enumerate(entries, start=1)
                    )
                )
                for at, entries in RADARS.items()
            },
            now=NOW,
        )
