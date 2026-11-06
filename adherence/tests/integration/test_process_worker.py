"""The process_worker WorkerPort: the shared contract over a real child
process, and a job that never returns ended at the deadline, its child
reaped, with the checks it finished. Every run here is bounded by its
deadline and watched from a daemon thread, so a broken worker fails the
test instead of hanging the suite."""

from __future__ import annotations

import multiprocessing
import os
import pickle
import signal
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from adherence.adapters.process_worker import UNREPORTED, ProcessWorker, receive
from adherence.domain.deadline import Deadline
from adherence.domain.report import Report
from adherence.ports.worker import Ended, Failed, Job, WorkerPort
from tests.worker_contract import ROOM, WorkerContract
from tests.worker_jobs import (
    FIRST,
    NOTED,
    REPORT,
    UNREAD,
    Dies,
    Finishes,
    NeverReturns,
    SpawnsThenDies,
)

# Room for a child process to start and report its first check.
BOUND = 1.0
# How long past the deadline a worker may take to end and reap its child.
GRACE = 15.0
# How long a killed orphan may take to be reaped by init.
REAPED_WITHIN = 5.0


class TestProcessWorker(WorkerContract):
    def port(self) -> WorkerPort:
        return ProcessWorker()


def _watched(job: Job, deadline: Deadline) -> Report | Ended | Failed | None:
    """The worker's answer, or None when it did not answer within GRACE of
    the deadline."""
    answers: list[Report | Ended | Failed] = []
    thread = threading.Thread(
        target=lambda: answers.append(ProcessWorker().run(job, deadline)),
        daemon=True,
    )
    thread.start()
    thread.join(deadline.epoch_seconds - time.time() + GRACE)
    return answers[0] if answers else None


def _is_running(pid: int) -> bool:
    """Whether a process with that pid exists; a zombie still does."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _gone_within(pid: int, seconds: float) -> bool:
    """Whether the process is gone, waiting at most `seconds` for init to
    reap it."""
    give_up = time.monotonic() + seconds
    while _is_running(pid):
        if time.monotonic() > give_up:
            return False
        time.sleep(0.05)
    return True


def test_run_of_a_job_that_never_returns_is_ended_and_reaped(
    tmp_path: Path,
) -> None:
    """Given a job that reports one check and then never returns, When the
    worker runs it under a short deadline, Then it is ended at the deadline,
    the answer is Ended with the check it finished and the run's coverage
    and notices, and its child process is gone, reaped rather than left a
    zombie."""
    pid_file = tmp_path / "pid"
    deadline = Deadline(epoch_seconds=time.time() + BOUND)

    answer = _watched(NeverReturns(pid_file), deadline)

    assert answer is not None, "the worker did not end the job"
    assert isinstance(answer, Ended), answer
    assert answer.finished == (FIRST,)
    assert answer.coverage == UNREAD.coverage
    assert answer.notices == NOTED.notices
    assert time.time() < deadline.epoch_seconds + GRACE
    assert not _is_running(int(pid_file.read_text(encoding="utf-8")))


def test_run_of_a_job_whose_process_dies_is_failed() -> None:
    """Given a job whose process dies after reporting one check, well before
    the deadline, When the worker runs it, Then the answer is Failed, saying
    the process ended unreported -- not Ended, which is the deadline's."""
    deadline = Deadline(epoch_seconds=time.time() + ROOM)

    answer = _watched(Dies(), deadline)

    assert answer is not None, "the worker did not answer"
    assert isinstance(answer, Failed), answer
    assert "ended unreported" in answer.reason


def test_run_of_a_job_that_dies_ends_the_analyzer_it_started(tmp_path: Path) -> None:
    """Given a job that starts a long-lived analyzer in its process group
    and then dies, When the worker answers, Then the analyzer is ended with
    the group, not left running under init."""
    pid_file = tmp_path / "pid"
    deadline = Deadline(epoch_seconds=time.time() + ROOM)

    answer = _watched(SpawnsThenDies(pid_file), deadline)

    assert answer is not None, "the worker did not answer"
    analyzer = int(pid_file.read_text(encoding="utf-8"))
    try:
        assert _gone_within(analyzer, REAPED_WITHIN), "the analyzer outlived its job"
    finally:
        if _is_running(analyzer):
            os.kill(analyzer, signal.SIGKILL)


PLANTED = """from pathlib import Path
Path({marker!r}).write_text("ran", encoding="utf-8")
"""


def test_run_from_a_repository_cwd_imports_nothing_from_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Given a cwd -- the repository root the hook runs in -- that holds a
    planted `multiprocessing` package, When the worker runs a job from it,
    Then the child imports nothing from that cwd: the planted code never
    runs and the job's Report comes back."""
    planted = tmp_path / "repo"
    (planted / "multiprocessing").mkdir(parents=True)
    marker = tmp_path / "marker"
    (planted / "multiprocessing" / "__init__.py").write_text(
        PLANTED.format(marker=str(marker)), encoding="utf-8"
    )
    monkeypatch.chdir(planted)
    deadline = Deadline(epoch_seconds=time.time() + ROOM)

    answer = _watched(Finishes(), deadline)

    assert not marker.exists(), "the child ran code from the repository's cwd"
    assert answer == REPORT, answer
    assert Path.cwd() == planted


def _frames(write: bytes) -> Failed | object:
    """What the worker makes of a pipe that carries `write` and then ends."""
    receiving, sending = multiprocessing.Pipe(duplex=False)
    try:
        os.write(sending.fileno(), write)
        sending.close()
        return receive(receiving)
    finally:
        receiving.close()


def _frame(payload: bytes) -> bytes:
    """One whole frame as a Connection writes it: a length, then the bytes."""
    return struct.pack("!i", len(payload)) + payload


@pytest.mark.parametrize(
    "write",
    [
        pytest.param(_frame(pickle.dumps(REPORT))[:12], id="cut-mid-frame"),
        pytest.param(b"", id="no-frame"),
        pytest.param(_frame(b"not a pickle"), id="not-a-pickle"),
        pytest.param(_frame(b"cno_such_module\nThing\n."), id="unknown-module"),
        pytest.param(_frame(b"cbuiltins\nno_such_name\n."), id="unknown-name"),
    ],
)
def test_receive_of_a_message_that_cannot_be_read_is_failed(write: bytes) -> None:
    """Given a pipe whose child was killed partway through a send, or that
    carries bytes that do not unpickle to a message, When the worker reads
    it, Then the answer is Failed, the process ended unreported -- never an
    exception that escapes the run."""
    answer = _frames(write)

    assert answer == Failed(UNREPORTED), answer


def test_receive_of_a_whole_message_is_that_message() -> None:
    """Given a pipe that carries one whole message, When the worker reads
    it, Then the answer is that message."""
    assert _frames(_frame(pickle.dumps(REPORT))) == REPORT


# A parent that runs a job that never returns through the worker.
PARENT = """import sys
import time
from pathlib import Path

from adherence.adapters.process_worker import ProcessWorker
from adherence.domain.deadline import Deadline
from tests.worker_jobs import NeverReturns

if __name__ == "__main__":
    deadline = Deadline(epoch_seconds=time.time() + 120)
    ProcessWorker().run(NeverReturns(Path(sys.argv[1])), deadline)
"""
# How long the parent may take to start its child and the child its job.
STARTED_WITHIN = 30.0


def _pid_within(pid_file: Path, seconds: float) -> int | None:
    """The pid the job wrote, waiting at most `seconds` for it."""
    give_up = time.monotonic() + seconds
    while time.monotonic() < give_up:
        text = pid_file.read_text(encoding="utf-8") if pid_file.exists() else ""
        if text:
            return int(text)
        time.sleep(0.05)
    return None


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGHUP])
def test_run_whose_parent_is_terminated_ends_the_child(
    tmp_path: Path, signum: signal.Signals
) -> None:
    """Given a parent running a job that never returns through the worker,
    When the parent is sent SIGTERM or SIGHUP, Then it ends with that signal
    and the worker's child -- which leads its own process group -- is
    gone with it, not left running under init."""
    scratch = tmp_path / "cwd"
    scratch.mkdir()
    script = tmp_path / "parent.py"
    script.write_text(PARENT, encoding="utf-8")
    pid_file = tmp_path / "pid"
    environment = {
        **os.environ,
        "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
    }
    parent = subprocess.Popen(
        [sys.executable, str(script), str(pid_file)],
        cwd=scratch,
        env=environment,
        stdin=subprocess.DEVNULL,
    )
    child: int | None = None
    try:
        child = _pid_within(pid_file, STARTED_WITHIN)
        assert child is not None, "the job never started"
        parent.send_signal(signum)
        assert parent.wait(timeout=GRACE) == -signum
        assert _gone_within(child, REAPED_WITHIN), "the child outlived its parent"
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=GRACE)
        if child is not None and _is_running(child):
            os.kill(child, signal.SIGKILL)
