"""The inline_worker WorkerPort, the fake: the shared contract, and the
script that ends a job after a count of finished checks."""

from __future__ import annotations

from adherence.adapters.inline_worker import FakeWorker
from adherence.container import SHIPPED_VOCABULARY
from adherence.domain.deadline import Deadline
from adherence.ports.worker import Ended, WorkerPort
from tests.worker_contract import WorkerContract
from tests.worker_jobs import FIRST, NOTED, UNREAD, Finishes


class TestFakeWorker(WorkerContract):
    def port(self) -> WorkerPort:
        return FakeWorker()


def test_run_scripted_to_end_after_one_check_returns_it_ended() -> None:
    """Given a worker scripted to end the job after one check, When it runs
    a job that reports its run's coverage, its notices and one check, Then
    the answer is Ended with that check, that coverage and those notices."""
    ended = FakeWorker(ends_after=1).run(Finishes(), Deadline(epoch_seconds=1.0))

    assert isinstance(ended, Ended)
    assert ended.finished == (FIRST,)
    assert ended.coverage == UNREAD.coverage
    assert ended.notices == NOTED.notices


def test_the_inline_worker_is_named_as_the_shipped_vocabulary_names_a_fake() -> None:
    """Given the fake behind WorkerPort, When its name is read against the
    shipped vocabulary, Then it carries a fake prefix and ends with the
    port's stem, so Swap finds WorkerPort faked."""
    name = FakeWorker.__name__

    assert any(name.startswith(prefix) for prefix in SHIPPED_VOCABULARY.fakes)
    assert name.endswith(WorkerPort.__name__.removesuffix("Port"))
