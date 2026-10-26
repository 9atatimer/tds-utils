"""The task's done condition, held for every unit test: the unit tier never
calls the network or spawns a process, so it never reaches a judge or loads
a model's weights. Every unit test runs behind tests/unit_tier.py's guard
(tests/unit/conftest.py); the judge's real-model runs live in
tests/integration/, marked integration."""

from __future__ import annotations

import socket
import subprocess

import pytest

from tests.unit_tier import UnitTierLeak


def test_unit_tier_refuses_the_network() -> None:
    """Given a unit test, When it opens a connection, Then the guard refuses
    it before any packet leaves, naming the tier."""
    with pytest.raises(UnitTierLeak, match="unit tier"):
        socket.create_connection(("127.0.0.1", 9), timeout=0.1)
    with pytest.raises(UnitTierLeak, match="unit tier"):
        socket.socket().connect(("127.0.0.1", 9))


def test_unit_tier_refuses_a_process() -> None:
    """Given a unit test, When it spawns a process (the decide client, an
    analyzer), Then the guard refuses it, naming the tier."""
    with pytest.raises(UnitTierLeak, match="unit tier"):
        subprocess.run(["true"], check=False)
    with pytest.raises(UnitTierLeak, match="unit tier"):
        subprocess.Popen(["true"])
