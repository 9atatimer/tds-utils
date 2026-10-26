"""WorkerPort's contract, written once and run against every adapter.

What every worker promises: a job that finishes by the deadline comes
back as its own Report, whatever it reported on the way. A subclass
supplies `port`.
"""

from __future__ import annotations

import time

from adherence.domain.deadline import Deadline
from adherence.ports.worker import WorkerPort
from tests.worker_jobs import REPORT, Finishes

# Long enough for a child process to start and finish a trivial job.
ROOM = 30.0


class WorkerContract:
    def port(self) -> WorkerPort:
        raise NotImplementedError("a contract subclass supplies its adapter")

    def test_run_of_a_job_that_finishes_returns_its_report(self) -> None:
        """Given a job that finishes well before the deadline, When the
        worker runs it, Then the answer is the job's own Report."""
        deadline = Deadline(epoch_seconds=time.time() + ROOM)

        assert self.port().run(Finishes(), deadline) == REPORT
