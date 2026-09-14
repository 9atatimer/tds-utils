"""SubprocessRunner against real processes (real time, so integration/)."""

from __future__ import annotations

import os
import time

from chores.adapters.process import SubprocessRunner
from chores.ports.process import ProcessRequest

ENV = {"PATH": "/usr/bin:/bin"}


def test_spawn_captures_streams_exit_code_and_identity() -> None:
    running = SubprocessRunner().spawn(
        ProcessRequest(
            ["sh", "-c", "echo out; echo err >&2; exit 3"],
            cwd="/",
            env=ENV,
            timeout_sec=10,
            kill_grace_sec=1,
        )
    )
    assert running.identity.pid > 0 and running.identity.pgid == running.identity.pid
    result = running.wait()
    assert (result.exit_code, result.stdout, result.stderr) == (3, "out\n", "err\n")
    assert result.timed_out is False and result.seconds >= 0


def test_stdin_text_reaches_the_child() -> None:
    running = SubprocessRunner().spawn(
        ProcessRequest(
            ["cat"],
            cwd="/",
            env=ENV,
            timeout_sec=10,
            kill_grace_sec=1,
            stdin_text="ping",
        )
    )
    assert running.wait().stdout == "ping"


def test_timeout_kills_the_whole_process_group() -> None:
    """Given a shell that spawns a sleeping grandchild, When the timeout hits,
    Then the grandchild is gone too (session kill, not pid kill)."""
    runner = SubprocessRunner()
    running = runner.spawn(
        ProcessRequest(
            ["sh", "-c", "sleep 30 & echo $!; wait"],
            cwd="/",
            env=ENV,
            timeout_sec=1,
            kill_grace_sec=1,
        )
    )
    result = running.wait()
    assert result.timed_out is True
    grandchild = int(result.stdout.strip().splitlines()[0])
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            os.kill(grandchild, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        raise AssertionError("grandchild survived the group kill")
    assert (
        runner.alive(running.identity.pid, process_start=running.identity.process_start)
        is False
    )


def test_alive_uses_start_time_to_reject_a_reused_pid() -> None:
    runner = SubprocessRunner()
    me = runner.own_identity()
    assert runner.alive(me.pid, process_start=me.process_start) is True
    assert runner.alive(me.pid, process_start=me.process_start + 1000) is False
