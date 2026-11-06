"""adapters/process_worker.py -- WorkerPort over a child process.

The hook's worker (ARCHITECTURE.ARCH-ADHERENCE.md, Module map and Key
Decisions: the bound is a deadline, not a clock): the job runs in a child
process that sends each check down a pipe as it finishes and its Report
last. At the deadline the child is ended -- with the process group it
leads, so an analyzer it spawned goes too -- and reaped, and the answer is
Ended with the checks that came down the pipe first. A pure check that
does not return is ended like any other. A job that raises, or a child
that dies -- even partway through a send -- before the deadline is Failed.
The clock is the edge's own.

The hook runs in the repository's root, and the code there is untrusted
(ARCHITECTURE.ARCH-ADHERENCE.md, Security mitigations). A spawned child
puts its cwd first on its import path and starts in its parent's cwd, so
the child is started from a fresh scratch directory outside the
repository, and drops every relative import path entry and moves to that
directory itself before it runs the job: nothing the repository holds is
imported. The job therefore names the repository by its absolute path.

While a run is in progress in the main thread, a SIGTERM or SIGHUP of the
parent ends the child's group before the signal takes its course, so the
child and the analyzers it started do not outlive it. A SIGKILL of the
parent cannot be caught: the child's group then outlives it, the limit of
a child that leads its own group.
"""

from __future__ import annotations

import contextlib
import multiprocessing
import os
import pickle
import signal
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from types import FrameType
from typing import Final

from adherence.domain.coverage import Coverage
from adherence.domain.deadline import Deadline
from adherence.domain.finding import Notice
from adherence.domain.report import FinishedCheck, Report, RunCoverage, RunNotices
from adherence.ports.worker import Ended, Failed, Job, Reported

# --- Constants ---------------------------------------------------------------

# A fresh interpreter per run on every platform: nothing of the parent's
# state but the job itself reaches the child.
START_METHOD: Final = "spawn"
# How long a child that sent its Report may take to exit before it is ended.
EXIT_GRACE = 5.0
AT_DEADLINE = "ended at the deadline"
UNREPORTED = "the job's process ended unreported"
# The parent's signals that end the child's group before they take effect.
ENDING_SIGNALS: Final = (signal.SIGTERM, signal.SIGHUP)
# What reading a message the child did not finish sending, or one that does
# not unpickle to a message, raises.
UNREADABLE: Final = (
    OSError,
    EOFError,
    pickle.UnpicklingError,
    AttributeError,
    ImportError,
)

# --- Values ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Failed:
    """The child's last word when the job raised instead of returning."""

    reason: str


class _PipeSink:
    """The sink a job is handed in the child: the run's coverage and
    notices and each check down the pipe."""

    def __init__(self, sending: Connection) -> None:
        self._sending = sending

    def __call__(self, check: Reported) -> None:
        self._sending.send(check)


# --- Effectful helpers -------------------------------------------------------


def _isolate(scratch: str) -> None:
    """Import nothing from a cwd: drop the cwd and every relative entry from
    the import path, and move to the scratch directory."""
    sys.path[:] = [entry for entry in sys.path if os.path.isabs(entry)]
    os.chdir(scratch)


def serve(job: Job, sending: Connection, scratch: str) -> None:
    """The child's whole life: import nothing from a cwd, lead its own
    process group, run the job, send its Report, or why it failed, and close
    the pipe."""
    _isolate(scratch)
    os.setpgid(0, 0)
    try:
        report = job(_PipeSink(sending))
        sending.send(report)
    except Exception as error:  # the job's boundary: anything it raises
        sending.send(_Failed(f"the job failed: {type(error).__name__}: {error}"))
    finally:
        sending.close()


def receive(receiving: Connection) -> object:
    """The next message down the pipe, or Failed when the child ended
    before it finished sending one or sent bytes that are no message."""
    try:
        return receiving.recv()
    except UNREADABLE:
        return Failed(UNREPORTED)


@contextlib.contextmanager
def _started_in(scratch: str) -> Iterator[None]:
    """The parent in the scratch directory while it starts the child, so
    the child's cwd and its first import path entry are there."""
    previous = os.getcwd()
    os.chdir(scratch)
    try:
        yield
    finally:
        os.chdir(previous)


def _handler(
    found: Callable[[int, FrameType | None], object] | int | None,
) -> Callable[[int, FrameType | None], object] | int:
    """A handler as `signal.signal` takes it back: one Python did not set
    is the default."""
    return signal.SIG_DFL if found is None else found


@contextlib.contextmanager
def _ending_on_signals(child: BaseProcess) -> Iterator[None]:
    """While the run is in progress, a SIGTERM or SIGHUP of the parent ends
    the child's group, then takes its course under the handler it replaced.
    Signal handlers can be set only in the main thread; elsewhere nothing
    changes."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    def ending(signum: int, _frame: FrameType | None) -> None:
        if child.pid is not None:
            end(child)
        signal.signal(signum, previous[signum])
        os.kill(os.getpid(), signum)

    previous: dict[int, Callable[[int, FrameType | None], object] | int] = {
        signum: _handler(signal.getsignal(signum)) for signum in ENDING_SIGNALS
    }
    for ending_signal in ENDING_SIGNALS:
        signal.signal(ending_signal, ending)
    try:
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def end(child: BaseProcess) -> None:
    """End the child and every process in the group it leads, then reap it.
    The group is ended whether or not the child is still alive: a child
    that died leaves its descendants -- an analyzer it started -- in it."""
    pid = child.pid
    if pid is not None:
        try:
            os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            # No such group: the child never made it, or it and everything
            # in it are gone. End the child alone if it is still there.
            if child.is_alive():
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
    ) -> Report | Ended | Failed:
        """Read the pipe until the Report, the deadline, or the child's end."""
        coverage: list[Coverage] = []
        notices: list[Notice] = []
        while True:
            left = deadline.epoch_seconds - self._clock()
            if left <= 0 or not receiving.poll(left):
                return Ended(
                    tuple(finished), AT_DEADLINE, tuple(coverage), tuple(notices)
                )
            message = receive(receiving)
            if isinstance(message, Report | Failed):
                return message
            if isinstance(message, _Failed):
                return Failed(message.reason)
            if isinstance(message, RunCoverage):
                coverage.extend(message.coverage)
                continue
            if isinstance(message, RunNotices):
                notices.extend(message.notices)
                continue
            if not isinstance(message, FinishedCheck):
                return Failed(UNREPORTED)
            finished.append(message)

    def run(self, job: Job, deadline: Deadline) -> Report | Ended | Failed:
        context = multiprocessing.get_context(START_METHOD)
        with tempfile.TemporaryDirectory(prefix="adhere-worker-") as scratch:
            receiving, sending = context.Pipe(duplex=False)
            child = context.Process(
                target=serve, args=(job, sending, scratch), daemon=True
            )
            finished: list[FinishedCheck] = []
            with _ending_on_signals(child):
                try:
                    with _started_in(scratch):
                        child.start()
                    sending.close()
                    answer = self._collect(receiving, deadline, finished)
                    if isinstance(answer, Report):
                        child.join(EXIT_GRACE)
                finally:
                    if child.pid is not None:
                        end(child)
                    receiving.close()
        return answer
