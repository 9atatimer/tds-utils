"""adapters/process_worker.py -- WorkerPort over a child process.

The hook's worker (ARCHITECTURE.ARCH-ADHERENCE.md, Module map and Key
Decisions: the bound is a deadline, not a clock): the job runs in a child
process that sends each check down a pipe as it finishes and its Report
last. At the deadline the child is ended -- with the process group it
leads, so an analyzer it spawned goes too -- and reaped, and the answer is
Ended with the checks that came down the pipe first. A pure check that
does not return is ended like any other. The clock is the edge's own.
"""

from __future__ import annotations

import multiprocessing
import os
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from typing import Final

from adherence.domain.deadline import Deadline
from adherence.domain.report import FinishedCheck, Report
from adherence.ports.worker import Ended, Job

# --- Constants ---------------------------------------------------------------

# A fresh interpreter per run on every platform: nothing of the parent's
# state but the job itself reaches the child.
START_METHOD: Final = "spawn"
# How long a child that sent its Report may take to exit before it is ended.
EXIT_GRACE = 5.0
AT_DEADLINE = "ended at the deadline"

# --- Values ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Failed:
    """The child's last word when the job raised instead of returning."""

    reason: str


class _PipeSink:
    """The sink a job is handed in the child: each check down the pipe."""

    def __init__(self, sending: Connection) -> None:
        self._sending = sending

    def __call__(self, check: FinishedCheck) -> None:
        self._sending.send(check)


# --- Effectful helpers -------------------------------------------------------


def serve(job: Job, sending: Connection) -> None:
    """The child's whole life: lead its own process group, run the job,
    send its Report, or why it failed, and close the pipe."""
    os.setpgid(0, 0)
    try:
        report = job(_PipeSink(sending))
        sending.send(report)
    except Exception as error:  # the job's boundary: anything it raises
        sending.send(_Failed(f"{type(error).__name__}: {error}"))
    finally:
        sending.close()


def end(child: BaseProcess) -> None:
    """End the child and every process in the group it leads, then reap it."""
    pid = child.pid
    if pid is not None and child.is_alive():
        try:
            os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            # The child has not yet made its group: end it alone.
            child.kill()
    child.join()


# --- Adapter -----------------------------------------------------------------


class ProcessWorker:
    """WorkerPort that runs the job in a child process, ended at the deadline."""

    def __init__(self, *, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock

    def _collect(
        self,
        receiving: Connection,
        deadline: Deadline,
        finished: list[FinishedCheck],
    ) -> Report | Ended:
        """Read the pipe until the Report, the deadline, or the child's end."""
        while True:
            left = deadline.epoch_seconds - self._clock()
            if left <= 0 or not receiving.poll(left):
                return Ended(tuple(finished), AT_DEADLINE)
            try:
                message = receiving.recv()
            except EOFError:
                return Ended(tuple(finished), "the job's process ended unreported")
            if isinstance(message, Report):
                return message
            if isinstance(message, _Failed):
                return Ended(tuple(finished), f"the job failed: {message.reason}")
            finished.append(message)

    def run(self, job: Job, deadline: Deadline) -> Report | Ended:
        context = multiprocessing.get_context(START_METHOD)
        receiving, sending = context.Pipe(duplex=False)
        child = context.Process(target=serve, args=(job, sending), daemon=True)
        child.start()
        sending.close()
        finished: list[FinishedCheck] = []
        try:
            answer = self._collect(receiving, deadline, finished)
            if isinstance(answer, Report):
                child.join(EXIT_GRACE)
        finally:
            end(child)
            receiving.close()
        return answer
