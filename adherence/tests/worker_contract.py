"""WorkerPort's contract, written once and run against every adapter.

What every worker promises: a job that finishes by the deadline comes
back as its own Report, whatever it reported on the way, and a job that
raises comes back Failed, naming why -- never Ended, which is the
deadline's answer alone. A subclass supplies `port`.
"""

from __future__ import annotations

import time

from adherence.domain.deadline import Deadline
from adherence.ports.worker import Failed, WorkerPort
from tests.worker_jobs import BROKE, REPORT, Finishes, Raises

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

    def test_run_of_a_job_that_raises_is_failed_naming_why(self) -> None:
        """Given a job that raises well before the deadline, When the worker
        runs it, Then the answer is Failed with the error, not Ended."""
        deadline = Deadline(epoch_seconds=time.time() + ROOM)

        answer = self.port().run(Raises(), deadline)

        assert isinstance(answer, Failed), answer
        assert BROKE in answer.reason
