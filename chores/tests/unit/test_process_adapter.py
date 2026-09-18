"""SubprocessRunner's process identity (CHORES.DESIGN.md Subsystem 3). The
real-process behaviors live in tests/integration/test_subprocess_runner.py;
what is pinned here is how identity fails when ``ps`` cannot answer.
"""

from __future__ import annotations

import pytest


def test_process_identity_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unknown recorded start, or a start ps cannot give now, never vouches
    for a pid: alive() is False, so the tick closes the run and kill never
    signals a possibly recycled group."""
    import os

    import chores.adapters.process as process
    from chores.adapters.process import UNKNOWN_START, SubprocessRunner

    runner = SubprocessRunner()
    me = os.getpid()
    assert runner.alive(me, process_start=UNKNOWN_START) is False
    monkeypatch.setattr(process, "process_start_time", lambda pid: None)
    assert runner.alive(me, process_start=12345.0) is False
    assert runner.own_identity().process_start == UNKNOWN_START  # not a guess
    monkeypatch.setattr(process, "process_start_time", lambda pid: 500.0)
    assert runner.alive(me, process_start=501.0) is True
    assert runner.alive(me, process_start=900.0) is False


def test_ps_is_read_in_the_c_locale(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    from chores.adapters.process import process_start_time

    seen: dict[str, str] = {}

    def fake_run(argv, **kw):  # type: ignore[no-untyped-def]
        seen.update(kw["env"])
        return subprocess.CompletedProcess(argv, 0, "Wed Sep 17 12:00:00 2026\n", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert process_start_time(1) is not None
    assert seen["LC_ALL"] == "C" and seen["LC_TIME"] == "C"
