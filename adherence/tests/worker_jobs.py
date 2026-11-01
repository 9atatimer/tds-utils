"""Jobs a WorkerPort is given in its tests: plain values at module level,
so process_worker can hand them to a child process."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from adherence.domain.coverage import Coverage
from adherence.domain.qualities import CATALOG
from adherence.domain.report import FinishedCheck, Report, RunCoverage
from adherence.ports.worker import FinishedSink

FIRST = FinishedCheck(CATALOG[0], ran=False)
REPORT = Report(repository="example", revision="c" * 40)
BROKE = "the engine broke"
# What a run could not cover outside any check, reported before its checks.
UNREAD = RunCoverage((Coverage("cannot be read: a symbolic link", path="x.py"),))


@dataclass(frozen=True)
class Finishes:
    """Reports the run's coverage and one check finished, then returns
    REPORT."""

    def __call__(self, finished: FinishedSink) -> Report:
        finished(UNREAD)
        finished(FIRST)
        return REPORT


@dataclass(frozen=True)
class NeverReturns:
    """Writes the pid of the process it runs in to `pid_file`, reports the
    run's coverage and one check finished, then waits for ever: a check
    that does not return."""

    pid_file: Path

    def __call__(self, finished: FinishedSink) -> Report:
        self.pid_file.write_text(str(os.getpid()), encoding="utf-8")
        finished(UNREAD)
        finished(FIRST)
        threading.Event().wait()
        return REPORT


@dataclass(frozen=True)
class Raises:
    """Reports one check finished, then raises: an engine that failed."""

    def __call__(self, finished: FinishedSink) -> Report:
        finished(FIRST)
        raise RuntimeError(BROKE)


@dataclass(frozen=True)
class Dies:
    """Reports one check finished, then ends its process without a word: a
    worker process that died."""

    def __call__(self, finished: FinishedSink) -> Report:
        finished(FIRST)
        os._exit(3)


@dataclass(frozen=True)
class SpawnsThenDies:
    """Starts a long-lived process in its own process group -- an analyzer
    still running -- writes that process's pid to `pid_file`, then ends its
    own process without a word."""

    pid_file: Path

    def __call__(self, finished: FinishedSink) -> Report:
        analyzer = subprocess.Popen(
            [sys.executable, "-I", "-c", "import time; time.sleep(600)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.pid_file.write_text(str(analyzer.pid), encoding="utf-8")
        os._exit(3)
