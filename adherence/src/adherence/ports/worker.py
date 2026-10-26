"""ports/worker.py -- WorkerPort: how a bounded run is ended.

process_worker runs a job in a child process and ends it at the deadline,
returning what the job reported before it was ended; inline_worker is the
fake, scriptable to end early (ARCHITECTURE.ARCH-ADHERENCE.md, Seams). A
job reports each check as it finishes through the sink it is handed, and
returns its Report if it is let finish.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from adherence.domain.deadline import Deadline
from adherence.domain.report import FinishedCheck, Report

# Where a job reports each check it finishes.
FinishedSink = Callable[[FinishedCheck], None]
# A bounded run's work: handed the sink, it returns its Report.
Job = Callable[[FinishedSink], Report]


@dataclass(frozen=True, slots=True)
class Ended:
    """A job the worker ended before it returned: the checks it reported
    finished, in order, and why it was ended."""

    finished: tuple[FinishedCheck, ...]
    reason: str


class WorkerPort(Protocol):
    def run(self, job: Job, deadline: Deadline) -> Report | Ended:
        """The job's Report when it finishes by the deadline; else Ended,
        with what it reported finished first."""
        ...
