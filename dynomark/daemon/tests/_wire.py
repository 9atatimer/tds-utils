"""Contract v1 request bodies for transport tests, built from domain values.

Every builder returns the UTF-8 JSON body of one frame (no length header).
"""

import json
from typing import Final

from dynomark_daemon.domain.batch import OpApplied, ReceiptApplied
from dynomark_daemon.domain.bookmark import Bookmark, Capture
from dynomark_daemon.domain.ids import BatchId, NodeId
from dynomark_daemon.domain.tree import Snapshot
from dynomark_daemon.wire.mapping import (
    bookmark_to_wire,
    capture_to_wire,
    folder_path_to_wire,
    receipt_to_wire,
    snapshot_to_wire,
)
from tests._factories import make_node, make_path, make_tree

URL: Final = "https://tokio.rs/tokio/tutorial"
TREE: Final = make_tree(
    make_node("10", "1", "Follow Up"),
    make_node("11", "1", "Dynomark", index=1),
    make_node("12", "1", "Graveyard", index=2),
    make_node("14", "11", "Rust"),
    make_node("13", "11", "dynomark-writer:mbp", index=1),
    make_node("42", "10", "Tokio tutorial", url=URL),
)
"""An established writer's tree: host ``mbp``'s marker is in Dynomark."""


def body(message_type: str, request_id: str, **fields: object) -> bytes:
    return json.dumps(
        {"v": 1, "type": message_type, "id": request_id, **fields}
    ).encode("utf-8")


def hello(request_id: str = "h-1", *, profile: str = "profile-a", v: int = 1) -> bytes:
    return json.dumps(
        {
            "v": v,
            "type": "hello",
            "id": request_id,
            "profile_id": profile,
            "follow_up": folder_path_to_wire(make_path("Follow Up")).model_dump(),
        }
    ).encode("utf-8")


def ingest(request_id: str, bookmark: Bookmark, capture: Capture) -> bytes:
    return body(
        "ingest",
        request_id,
        bookmark=bookmark_to_wire(bookmark).model_dump(by_alias=True),
        capture=capture_to_wire(capture).model_dump(by_alias=True),
        backfill=False,
    )


def tree_snapshot(request_id: str, tree: Snapshot = TREE) -> bytes:
    return body(
        "tree.snapshot",
        request_id,
        snapshot=snapshot_to_wire(tree).model_dump(by_alias=True),
    )


def applied_receipt(
    request_id: str, batch_id: str, node_ids: list[str], tree: Snapshot = TREE
) -> bytes:
    receipt = ReceiptApplied(
        batch_id=BatchId(batch_id),
        applied=tuple(
            OpApplied(index=i, node_id=NodeId(node_id), changed=True)
            for i, node_id in enumerate(node_ids)
        ),
        skipped=(),
        pre_batch=True,
        snapshot=tree,
    )
    return body(
        "batch.receipt",
        request_id,
        receipt=receipt_to_wire(receipt).model_dump(by_alias=True),
    )
