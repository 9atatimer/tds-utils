"""Framework wiring for the unit tier: every unit test runs behind the
no-network, no-process guard (tests/unit_tier.py)."""

from __future__ import annotations

import pytest

from tests.unit_tier import guard


@pytest.fixture(autouse=True)
def _unit_tier(monkeypatch: pytest.MonkeyPatch) -> None:
    guard(monkeypatch)
