"""The process_worker WorkerPort: the shared contract over a real child
process, and a job that never returns ended at the deadline, its child
reaped, with the checks it finished. Every run here is bounded by its
deadline and watched from a daemon thread, so a broken worker fails the
test instead of hanging the suite."""

from __future__ import annotations

import os
import signal
import threading
import time
from pathlib import Path

from adherence.adapters.process_worker import ProcessWorker
from adherence.domain.deadline import Deadline
from adherence.domain.report import Report
from adherence.ports.worker import Ended, Failed, Job, WorkerPort
from tests.worker_contract import ROOM, WorkerContract
from tests.worker_jobs import FIRST, UNREAD, Dies, NeverReturns, SpawnsThenDies

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
    the answer is Ended with the check it finished and the run's coverage,
    and its child process is gone, reaped rather than left a zombie."""
    pid_file = tmp_path / "pid"
    deadline = Deadline(epoch_seconds=time.time() + BOUND)

    answer = _watched(NeverReturns(pid_file), deadline)

    assert answer is not None, "the worker did not end the job"
    assert isinstance(answer, Ended), answer
    assert answer.finished == (FIRST,)
    assert answer.coverage == UNREAD.coverage
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
