"""The job loop's step killed part-way (DYNOMARK.DESIGN.md, The daemon:
"Durable jobs"; Transport contract, "Delivery": events are durable until
acknowledged). A restarted daemon's loop runs every due job again over the
same store; whatever the kill left, the job ends where an unkilled run
would have, with one batch offered and a ``job.updated`` for its state.
"""

import pytest

from dynomark_daemon.domain.events import BatchOffered, JobUpdated
from dynomark_daemon.domain.job import Job, JobState
from dynomark_daemon.domain.placement import FolderChoice
from dynomark_daemon.ports.completion import CompletionError
from dynomark_daemon.testing.completion import ScriptedCompletion
from tests._crash import DyingStore
from tests._factories import make_path
from tests.unit.app._loop import ENRICHMENT, RUST, TREE, Loop

CHOICE = FolderChoice(folder=RUST, rationale="rust")


def _points_at_a_batch(value: object) -> bool:
    return isinstance(value, Job) and value.batch_id is not None


def _is_a_job_update(value: object) -> bool:
    return isinstance(value, JobUpdated)


def _updates(loop: Loop) -> list[Job]:
    return [e.job for e in loop.events() if isinstance(e, JobUpdated)]


def _killed(loop: Loop, job: Job) -> None:
    with pytest.raises(SystemExit):
        loop.run(job)


def test_a_job_killed_before_it_points_at_its_offered_batch_offers_one_batch() -> None:
    """Given the daemon was killed after a job's batch was stored and offered and
    before the job pointed at it, When the restarted loop runs the job again,
    Then exactly one batch is offered and the job points at it."""
    store = DyingStore()
    completion = ScriptedCompletion(enrich=[ENRICHMENT], choose_folder=[CHOICE] * 2)
    loop = Loop(completion, TREE, store)
    job = loop.save()
    store.kill_at("put_job", _points_at_a_batch)
    _killed(loop, job)

    loop.run_due()

    offers = [e.batch for e in loop.events() if isinstance(e, BatchOffered)]
    batches = [r.batch for r in store.list_batches()]
    assert len(offers) == 1 and batches == offers
    stored = store.get_job(job.job_id)
    assert stored is not None and stored.batch_id == offers[0].batch_id


def test_a_backfill_killed_before_its_update_is_announced_indexed() -> None:
    """Given the daemon was killed after a backfill outside Dynomark was stored
    INDEXED and before its job.updated was, When the restarted loop runs, Then
    the extension is sent a job.updated for the INDEXED job (it re-pulls the
    index on one)."""
    store = DyingStore()
    loop = Loop(ScriptedCompletion(enrich=[ENRICHMENT] * 2), TREE, store)
    job = loop.save(make_path("Recipes"), backfill=True)
    store.kill_at("put_event", _is_a_job_update)
    _killed(loop, job)

    loop.run_due()

    assert [u.state for u in _updates(loop)] == [JobState.INDEXED]


def test_a_failed_enrichment_killed_before_its_update_is_announced_failed() -> None:
    """Given the daemon was killed after a job's enrichment failed for good and
    the job was stored FAILED, and before its job.updated was, When the
    restarted loop runs, Then the extension is sent a job.updated for the
    FAILED job."""
    store = DyingStore()
    refused = CompletionError("model refused", retryable=False)
    loop = Loop(ScriptedCompletion(enrich=[refused, refused]), TREE, store)
    job = loop.save()
    store.kill_at("put_event", _is_a_job_update)
    _killed(loop, job)

    loop.run_due()

    assert [u.state for u in _updates(loop)] == [JobState.FAILED]
