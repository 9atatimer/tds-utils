"""The unit tier's guard: no network, no process (the testing skill, Test
Layers: a unit test fakes every external dependency). tests/unit/conftest.py
installs it around every unit test; integration tests run without it."""

from __future__ import annotations

import socket
import subprocess

import pytest

REFUSAL = "the unit tier calls no network and spawns no process; use a fake"


class UnitTierLeak(AssertionError):
    """A unit test reached for the network or a process."""


def refuse(*args: object, **kwargs: object) -> None:
    raise UnitTierLeak(REFUSAL)


def guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refuse every connection and every spawn for the rest of the test."""
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)
