"""Behaviors row: A reader host never writes (DYNOMARK.DESIGN.md, Behaviors
and Interfaces; Goal 7) -- "Given role reader, When any of place, file,
undo, accept_diff_item runs, Then the result is NotWriter and no batch row
exists"; and State Machine: "ENRICHED -> INDEXED ... HostRole is reader;
terminal; place is not called"; The daemon, Durable jobs: "NotWriter is not
retryable and not counted". (undo is covered with its own row.)
"""

from dynomark_daemon.app.file import file, park
from dynomark_daemon.app.place import place
from dynomark_daemon.domain.bookmark import Save
from dynomark_daemon.domain.job import JobState
from dynomark_daemon.domain.roles import HostRole, NotWriter
from dynomark_daemon.testing.clock import FakeClock, SequentialIds
from dynomark_daemon.testing.completion import EnrichCall, ScriptedCompletion
from dynomark_daemon.testing.embedding import HashingEmbedding
from dynomark_daemon.testing.store import InMemoryCorpusStore
from tests._factories import (
    make_bookmark,
    make_capture,
    make_entry,
    make_job,
    make_outline,
    make_path,
    make_placement,
    make_roots,
)
from tests.unit.app._loop import ENRICHMENT, TREE, Loop


def test_place_on_a_reader_is_not_writer_and_records_nothing() -> None:
    """Given role reader, When an entry is placed, Then the result is NotWriter,
    no completion is asked and no placement is recorded."""
    store, completion = InMemoryCorpusStore(), ScriptedCompletion()
    entry = make_entry()

    result = place(
        entry,
        make_outline(),
        [],
        HostRole.READER,
        store=store,
        embedding=HashingEmbedding(),
        completion=completion,
        clock=FakeClock(),
    )

    assert isinstance(result, NotWriter)
    assert completion.calls == []
    assert store.get_placement(entry.identity) is None


def test_file_and_park_on_a_reader_are_not_writer_and_store_no_batch() -> None:
    """Given role reader, When a placement is filed or a duplicate parked, Then
    each result is NotWriter and no batch row or offer exists."""
    store = InMemoryCorpusStore()
    job = make_job(state=JobState.PLACED)
    store.put_job(job)
    store.put_save(job.job_id, Save(bookmark=make_bookmark(), capture=make_capture()))
    store.put_tree_snapshot(TREE)
    clock, ids = FakeClock(), SequentialIds()

    filed = file(
        make_placement(folder=make_path("Dynomark")),
        job,
        make_outline(),
        make_roots(),
        HostRole.READER,
        store=store,
        clock=clock,
        ids=ids,
    )
    parked = park(job, make_roots(), HostRole.READER, store=store, clock=clock, ids=ids)

    assert isinstance(filed, NotWriter) and isinstance(parked, NotWriter)
    assert store.list_batches() == []
    assert store.unacked_events(job.profile_id) == []


def test_run_job_on_a_reader_indexes_the_save_without_placing_it() -> None:
    """Given a queued save on a reader host, When the job loop runs it, Then the
    job reaches INDEXED, place is never called and no batch exists."""
    loop = Loop(ScriptedCompletion(enrich=[ENRICHMENT]), TREE)

    job = loop.run(loop.save(), HostRole.READER)

    assert job.state is JobState.INDEXED
    assert [type(call) for call in loop.completion.calls] == [EnrichCall]
    assert loop.store.get_placement(job.identity) is None
    assert loop.store.list_batches() == []


def test_run_job_on_a_reader_never_counts_or_fails_a_placed_job() -> None:
    """Given a PLACED job on a host now configured reader, When the job loop runs
    it, Then NotWriter is neither retried nor counted: the job keeps its state
    and attempts, and no batch exists."""
    loop = Loop(ScriptedCompletion(), TREE)
    job = make_job(state=JobState.PLACED)
    loop.store.put_job(job)
    loop.store.put_save(
        job.job_id, Save(bookmark=make_bookmark(), capture=make_capture())
    )
    loop.store.put_placement(make_placement(folder=make_path("Dynomark")))

    after = loop.run(job, HostRole.READER)

    assert after == job
    assert loop.store.list_batches() == []
