"""Jobs a WorkerPort is given in its tests: plain values at module level,
so process_worker can hand them to a child process."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path

from adherence.domain.qualities import CATALOG
from adherence.domain.report import FinishedCheck, Report
from adherence.ports.worker import FinishedSink

FIRST = FinishedCheck(CATALOG[0], ran=False)
REPORT = Report(repository="example", revision="c" * 40)
BROKE = "the engine broke"


@dataclass(frozen=True)
class Finishes:
    """Reports one check finished, then returns REPORT."""

    def __call__(self, finished: FinishedSink) -> Report:
        finished(FIRST)
        return REPORT


@dataclass(frozen=True)
class NeverReturns:
    """Writes the pid of the process it runs in to `pid_file`, reports one
    check finished, then waits for ever: a check that does not return."""

    pid_file: Path

    def __call__(self, finished: FinishedSink) -> Report:
        self.pid_file.write_text(str(os.getpid()), encoding="utf-8")
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
