"""ports/worker.py -- WorkerPort: how a bounded run is ended.

process_worker runs a job in a child process and ends it at the deadline,
returning what the job reported before it was ended; inline_worker is the
fake, scriptable to end early (ARCHITECTURE.ARCH-ADHERENCE.md, Seams). A
job reports the run's own coverage and then each check as it finishes
through the sink it is handed, and returns its Report if it is let
finish. A job that raises, or whose
process dies, is Failed: the engine could not measure, which is not the
deadline's Ended.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from adherence.domain.coverage import Coverage
from adherence.domain.deadline import Deadline
from adherence.domain.report import FinishedCheck, Report, RunCoverage

# Where a job reports its run's own coverage and each check it finishes.
FinishedSink = Callable[[FinishedCheck | RunCoverage], None]
# A bounded run's work: handed the sink, it returns its Report.
Job = Callable[[FinishedSink], Report]


@dataclass(frozen=True, slots=True)
class Ended:
    """A job the worker ended before it returned: the checks it reported
    finished, in order, why it was ended, and the run's own coverage it
    reported."""

    finished: tuple[FinishedCheck, ...]
    reason: str
    coverage: tuple[Coverage, ...] = ()


@dataclass(frozen=True, slots=True)
class Failed:
    """A job that neither returned nor was ended: it raised, or the process
    it ran in died. Why, as the reason a run that was not run names."""

    reason: str


class WorkerPort(Protocol):
    def run(self, job: Job, deadline: Deadline) -> Report | Ended | Failed:
        """The job's Report when it finishes by the deadline; Ended, with
        what it reported finished first, when the deadline ends it; Failed
        when it raises or its process dies first."""
        ...
