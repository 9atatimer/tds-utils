"""Wire <-> domain mapping (task-022, step 1: "Mapping between wire models
and domain values lives in wire/").

Where the domain value carries everything its wire model does, the mapping
is lossless both ways: every such value in the golden files survives
wire -> domain -> wire. Values the daemon only sends (a ``Job``, a
``WriteBatch`` without its inverse, a ``TreeDiff`` header, a batch
summary, an event) are checked from the domain side: any in-contract
domain value maps to a message that contract v1 accepts, keeping its ids.
"""

from collections.abc import Callable, Iterator

import pytest
from hypothesis import given, settings
from pydantic import BaseModel

from dynomark_daemon.domain.batch import BatchRecord, WriteBatch
from dynomark_daemon.domain.diff import TreeDiff
from dynomark_daemon.domain.events import BatchOffered, DiffProposed, Event, JobUpdated
from dynomark_daemon.domain.job import Job
from dynomark_daemon.testing import strategies
from dynomark_daemon.wire import mapping
from dynomark_daemon.wire import values as w
from dynomark_daemon.wire.codec import decode_body, encode_message
from dynomark_daemon.wire.messages import AnyMessage
from tests.contract.golden import valid_files

pytestmark = pytest.mark.contract

# Nested domain values are costly to draw; 25 examples keep each property
# under the unit-test budget while still covering every Operation kind.
FEW = settings(max_examples=25)

LOSSLESS: dict[type[BaseModel], tuple[Callable[..., object], Callable[..., object]]] = {
    w.FolderPath: (mapping.folder_path_from_wire, mapping.folder_path_to_wire),
    w.OwnedRoots: (mapping.owned_roots_from_wire, mapping.owned_roots_to_wire),
    w.Bookmark: (mapping.bookmark_from_wire, mapping.bookmark_to_wire),
    w.Capture: (mapping.capture_from_wire, mapping.capture_to_wire),
    w.Snapshot: (mapping.snapshot_from_wire, mapping.snapshot_to_wire),
    w.OutlineFolder: (mapping.outline_folder_from_wire, mapping.outline_folder_to_wire),
    w.Move: (mapping.move_from_wire, mapping.move_to_wire),
    w.ReceiptApplied: (mapping.receipt_from_wire, mapping.receipt_to_wire),
    w.ReceiptPartial: (mapping.receipt_from_wire, mapping.receipt_to_wire),
    w.ReceiptRejected: (mapping.receipt_from_wire, mapping.receipt_to_wire),
    w.OpCreateFolder: (mapping.operation_from_wire, mapping.operation_to_wire),
    w.OpCreate: (mapping.operation_from_wire, mapping.operation_to_wire),
    w.OpMove: (mapping.operation_from_wire, mapping.operation_to_wire),
    w.OpRemove: (mapping.operation_from_wire, mapping.operation_to_wire),
    w.UndoDrop: (mapping.undo_drop_from_wire, mapping.undo_drop_to_wire),
    w.LocalIndexRow: (
        mapping.local_index_row_from_wire,
        mapping.local_index_row_to_wire,
    ),
    w.CorpusHit: (mapping.hit_from_wire, mapping.corpus_hit_to_wire),
    w.EntryRef: (mapping.citation_from_wire, mapping.citation_to_wire),
    w.Turn: (mapping.turn_from_wire, mapping.turn_to_wire),
    w.Answer: (mapping.answer_from_wire, mapping.answer_to_wire),
    w.PlacementReason: (mapping.placement_from_wire, mapping.placement_to_wire),
    w.ModelInfo: (mapping.model_info_from_wire, mapping.model_info_to_wire),
}


def _sub_models(model: object) -> Iterator[BaseModel]:
    if isinstance(model, BaseModel):
        yield model
        for name in type(model).model_fields:
            yield from _sub_models(getattr(model, name))
    elif isinstance(model, list):
        for item in model:
            yield from _sub_models(item)


def _golden_values() -> list[tuple[str, BaseModel]]:
    found: list[tuple[str, BaseModel]] = []
    for path in valid_files():
        for model in _sub_models(decode_body(path.read_bytes())):
            if type(model) in LOSSLESS:
                found.append((f"{path.name}:{type(model).__name__}", model))
    return found


GOLDEN = _golden_values()


def test_golden_files_exercise_every_lossless_mapping() -> None:
    """Given the valid golden files, When their values are collected, Then every
    lossless mapping has at least one instance to round-trip."""
    assert {type(model) for _, model in GOLDEN} == set(LOSSLESS)


@pytest.mark.parametrize("model", [m for _, m in GOLDEN], ids=[n for n, _ in GOLDEN])
def test_map_golden_value_through_domain_returns_the_same_wire_value(
    model: BaseModel,
) -> None:
    """Given a wire value from a golden file, When mapped to the domain and back,
    Then it is unchanged (nothing the contract carries is lost)."""
    from_wire, to_wire = LOSSLESS[type(model)]

    assert to_wire(from_wire(model)) == model


def _round_trips(message: AnyMessage) -> bool:
    return decode_body(encode_message(message)) == message


@FEW
@given(strategies.jobs)
def test_map_job_to_wire_yields_a_contract_valid_job(job: Job) -> None:
    """Given any in-contract Job, When mapped to the wire, Then contract v1
    accepts it and it names the same job, node, identity and state."""
    wire = mapping.job_to_wire(job)

    assert (wire.job_id, wire.node_id, wire.identity, wire.state) == (
        job.job_id,
        job.node_id,
        job.identity.value,
        job.state.value,
    )
    assert w.Job.model_validate_json(wire.model_dump_json()) == wire


@FEW
@given(strategies.write_batches)
def test_map_write_batch_to_wire_offers_its_operations_not_its_inverse(
    batch: WriteBatch,
) -> None:
    """Given a WriteBatch, When mapped to the wire, Then the offer carries its
    operations in order and its item reference; the inverse stays home."""
    wire = mapping.write_batch_to_wire(batch)

    assert wire.batch_id == batch.batch_id
    assert [mapping.operation_from_wire(op) for op in wire.operations] == list(
        batch.operations
    )
    assert wire.diff_item_id == batch.diff_item_id


@FEW
@given(strategies.tree_diffs)
def test_map_tree_diff_to_wire_counts_items_and_unaccepted_items(
    diff: TreeDiff,
) -> None:
    """Given a TreeDiff, When mapped to its wire header, Then item_count and
    unaccepted_count are counted from its items."""
    wire = mapping.tree_diff_to_wire(diff)

    assert wire.item_count == len(diff.items)
    assert wire.unaccepted_count == sum(i.accepted_at is None for i in diff.items)


@FEW
@given(strategies.batch_records)
def test_map_batch_record_to_wire_summarizes_it(record: BatchRecord) -> None:
    """Given a BatchRecord, When summarized for batch.list, Then the summary
    names its batch, state, job, identity, item and undo links."""
    wire = mapping.batch_summary_to_wire(record)

    assert (wire.batch_id, wire.state, wire.created_at) == (
        record.batch.batch_id,
        record.state.value,
        record.created_at,
    )
    assert wire.identity == (record.identity.value if record.identity else None)
    assert (wire.job_id, wire.diff_item_id, wire.undoes, wire.undone_by) == (
        record.job_id,
        record.batch.diff_item_id,
        record.undoes,
        record.undone_by,
    )


@FEW
@given(strategies.events)
def test_map_event_to_wire_yields_its_event_message(event: Event) -> None:
    """Given a domain Event, When mapped, Then it is the matching event message
    (job.updated, batch.offer, diff.proposed) with its event id, and it
    survives the codec."""
    message = mapping.event_to_wire(event)
    expected = {
        JobUpdated: "job.updated",
        BatchOffered: "batch.offer",
        DiffProposed: "diff.proposed",
    }[type(event)]

    assert (message.type, message.event_id) == (expected, event.event_id)
    assert _round_trips(message)
