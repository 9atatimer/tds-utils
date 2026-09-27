"""Behaviors row: A placement is explained (DYNOMARK.DESIGN.md, Behaviors and
Interfaces) -- ``explain_placement(identity, *, store)``: "Given a filed
entry, When explained, Then the reason names the folder, neighbours and
feedback used". Contract v1 ``placement.explain`` names the entry by
identity or by raw url; an entry with no placement is ``not_found``.
"""

import pytest

from dynomark_daemon.app.errors import UnknownRecord
from dynomark_daemon.app.explain import explain_placement
from dynomark_daemon.domain.bookmark import Identity
from dynomark_daemon.domain.ids import FeedbackId
from dynomark_daemon.domain.placement import EntryRef, Placement, PlacementReason
from dynomark_daemon.testing.store import InMemoryCorpusStore
from tests._factories import make_path

RUST = make_path("Dynomark", "Rust")
URL = "https://tokio.rs/tokio/tutorial"


def _placed() -> tuple[InMemoryCorpusStore, Placement]:
    store = InMemoryCorpusStore()
    placement = Placement(
        identity=Identity(URL),
        reason=PlacementReason(
            folder=RUST,
            neighbours=(
                EntryRef(Identity("https://docs.rs/tokio"), "tokio docs", RUST),
            ),
            rationale="next to the other tokio pages",
            feedback_ids=(FeedbackId("fb-7-1"),),
            model_id="llama3.1:8b",
        ),
        created_at=5,
    )
    store.put_placement(placement)
    return store, placement


def test_explain_placement_names_folder_neighbours_feedback_and_model() -> None:
    """Given a filed entry, When explained, Then the reason names its folder,
    the neighbours and feedback used, and the model that chose."""
    store, placement = _placed()

    explained = explain_placement(Identity(URL), store=store)

    assert explained == placement
    assert explained.reason.model_id == "llama3.1:8b"


def test_explain_placement_by_raw_url_normalizes_it_first() -> None:
    """Given a filed entry, When explained by a raw url variant of it, Then the
    same placement is returned (the daemon owns normalization)."""
    store, placement = _placed()

    explained = explain_placement(
        Identity.from_url("HTTPS://Tokio.RS:443/tokio/tutorial"), store=store
    )

    assert explained == placement


def test_explain_placement_of_an_unplaced_identity_is_unknown() -> None:
    """Given no placement for an identity, When explained, Then UnknownRecord."""
    with pytest.raises(UnknownRecord):
        explain_placement(Identity("https://unplaced.example/"), store=_placed()[0])
