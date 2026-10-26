"""The process_worker WorkerPort: the shared contract over a real child
process, and a job that never returns ended at the deadline, its child
reaped, with the checks it finished. Every run here is bounded by its
deadline and watched from a daemon thread, so a broken worker fails the
test instead of hanging the suite."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from adherence.adapters.process_worker import ProcessWorker
from adherence.domain.deadline import Deadline
from adherence.domain.report import Report
from adherence.ports.worker import Ended, Job, WorkerPort
from tests.worker_contract import WorkerContract
from tests.worker_jobs import FIRST, NeverReturns

# Room for a child process to start and report its first check.
BOUND = 3.0
# How long past the deadline a worker may take to end and reap its child.
GRACE = 15.0


class TestProcessWorker(WorkerContract):
    def port(self) -> WorkerPort:
        return ProcessWorker()


def _watched(job: Job, deadline: Deadline) -> Report | Ended | None:
    """The worker's answer, or None when it did not answer within GRACE of
    the deadline."""
    answers: list[Report | Ended] = []
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


def test_run_of_a_job_that_never_returns_is_ended_and_reaped(
    tmp_path: Path,
) -> None:
    """Given a job that reports one check and then never returns, When the
    worker runs it under a short deadline, Then it is ended at the deadline,
    the answer is Ended with the check it finished, and its child process
    is gone, reaped rather than left a zombie."""
    pid_file = tmp_path / "pid"
    deadline = Deadline(epoch_seconds=time.time() + BOUND)

    answer = _watched(NeverReturns(pid_file), deadline)

    assert answer is not None, "the worker did not end the job"
    assert isinstance(answer, Ended), answer
    assert answer.finished == (FIRST,)
    assert time.time() < deadline.epoch_seconds + GRACE
    assert not _is_running(int(pid_file.read_text(encoding="utf-8")))
