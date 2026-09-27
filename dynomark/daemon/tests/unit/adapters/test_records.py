"""The SQLite store keeps domain values as JSON documents (adapters/records.py).

A document read back must be the value that was written: every field, every
nested union member, every enum and id. Round-trip over the domain's own
hypothesis strategies.
"""

import pytest
from hypothesis import given, settings

from dynomark_daemon.adapters.records import RecordError, dump_record, load_record
from dynomark_daemon.domain.batch import BatchRecord
from dynomark_daemon.domain.diff import TreeDiff
from dynomark_daemon.domain.events import BatchOffered, DiffProposed, Event, JobUpdated
from dynomark_daemon.domain.job import Job
from dynomark_daemon.domain.tree import Snapshot
from dynomark_daemon.testing import strategies as s
from tests._factories import make_job, make_node, make_snapshot, make_tree

EVENT_TYPES = (JobUpdated, BatchOffered, DiffProposed)


@settings(max_examples=60)
@given(record=s.batch_records)
def test_a_batch_record_round_trips(record: BatchRecord) -> None:
    """Given any batch record, When dumped and loaded, Then it is equal."""
    assert load_record(dump_record(record), BatchRecord) == record


@settings(max_examples=60)
@given(job=s.jobs)
def test_a_job_round_trips(job: Job) -> None:
    """Given any job, When dumped and loaded, Then it is equal."""
    assert load_record(dump_record(job), Job) == job


@settings(max_examples=40)
@given(diff=s.tree_diffs)
def test_a_tree_diff_round_trips(diff: TreeDiff) -> None:
    """Given any diff with its items, When dumped and loaded, Then it is equal."""
    assert load_record(dump_record(diff), TreeDiff) == diff


@settings(max_examples=60)
@given(event=s.events)
def test_an_event_round_trips_as_its_own_union_member(event: Event) -> None:
    """Given any event, When dumped and loaded as the Event union, Then it is
    equal and of the same type."""
    loaded = load_record(dump_record(event), Event, EVENT_TYPES)

    assert loaded == event and type(loaded) is type(event)


def test_a_snapshot_round_trips() -> None:
    """Given a snapshot with folders and bookmarks, When dumped and loaded,
    Then it is equal."""
    tree = make_tree(
        make_node("10", "1", "Follow Up"),
        make_node("42", "10", "Tokio", url="https://tokio.rs/"),
    )

    assert load_record(dump_record(tree), Snapshot) == tree
    assert load_record(dump_record(make_snapshot()), Snapshot) == make_snapshot()


def test_loading_a_document_of_another_type_raises() -> None:
    """Given a job's document, When loaded as a Snapshot, Then it raises
    RecordError instead of returning a wrong value."""
    with pytest.raises(RecordError):
        load_record(dump_record(make_job()), Snapshot)
