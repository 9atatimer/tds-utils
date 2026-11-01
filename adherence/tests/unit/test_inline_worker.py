"""The inline_worker WorkerPort, the fake: the shared contract, and the
script that ends a job after a count of finished checks."""

from __future__ import annotations

from adherence.adapters.inline_worker import InlineWorker
from adherence.domain.deadline import Deadline
from adherence.ports.worker import Ended, WorkerPort
from tests.worker_contract import WorkerContract
from tests.worker_jobs import FIRST, UNREAD, Finishes


class TestInlineWorker(WorkerContract):
    def port(self) -> WorkerPort:
        return InlineWorker()


def test_run_scripted_to_end_after_one_check_returns_it_ended() -> None:
    """Given a worker scripted to end the job after one check, When it runs
    a job that reports its run's coverage and one check, Then the answer is
    Ended with that check and that coverage."""
    ended = InlineWorker(ends_after=1).run(Finishes(), Deadline(epoch_seconds=1.0))

    assert isinstance(ended, Ended)
    assert ended.finished == (FIRST,)
    assert ended.coverage == UNREAD.coverage
