"""Behaviors row: A user move becomes feedback, daemon side (DYNOMARK.DESIGN.md,
Behaviors and Interfaces; The extension, "Record feedback": "only a Move of
origin user on the writer host becomes feedback (the daemon discards the
rest by HostRole)"; Ubiquitous language: MoveFeedback, "between two owned
folders"). Contract v1 ``move.observed`` is idempotent on (node_id,
observed_at). Goal 3: a filed bookmark's folder changes by a user move, so
its placement follows.
"""

from dynomark_daemon.app.feedback import record_feedback
from dynomark_daemon.domain.bookmark import Identity
from dynomark_daemon.domain.ids import NodeId
from dynomark_daemon.domain.placement import Move, MoveFeedback, MoveOrigin
from dynomark_daemon.domain.roles import HostRole
from dynomark_daemon.domain.tree import FolderPath
from dynomark_daemon.testing.store import InMemoryCorpusStore
from tests._factories import make_path, make_placement, make_roots

URL = "https://tokio.rs/tokio/tutorial"
RUST = make_path("Dynomark", "Rust")
ASYNC = make_path("Dynomark", "Rust", "Async")


def _move(
    *,
    origin: MoveOrigin = MoveOrigin.USER,
    url: str | None = URL,
    to: FolderPath = ASYNC,
) -> Move:
    return Move(
        node_id=NodeId("42"),
        from_path=RUST,
        to_path=to,
        origin=origin,
        observed_at=1_790_000_050_000,
        url=url,
    )


def _record(
    store: InMemoryCorpusStore, move: Move, role: HostRole = HostRole.WRITER
) -> MoveFeedback | None:
    return record_feedback(move, role, make_roots(), store=store)


def test_a_user_move_between_owned_folders_on_the_writer_is_feedback() -> None:
    """Given a user move of a filed bookmark between two owned folders on the
    writer, When recorded, Then feedback exists for its identity, and its
    placement follows the move."""
    store = InMemoryCorpusStore()
    store.put_placement(make_placement(URL, folder=RUST))

    feedback = _record(store, _move())

    assert feedback is not None
    assert (feedback.identity, feedback.from_path, feedback.to_path) == (
        Identity(URL),
        RUST,
        ASYNC,
    )
    assert store.recent_feedback(limit=10) == [feedback]
    placement = store.get_placement(Identity(URL))
    assert placement is not None and placement.folder == ASYNC
    assert placement.reason.feedback_ids == (feedback.feedback_id,)


def test_the_same_move_observed_twice_is_recorded_once() -> None:
    """Given a move already recorded, When the same (node, time) arrives again,
    Then there is still one feedback."""
    store = InMemoryCorpusStore()

    _record(store, _move())
    _record(store, _move())

    assert len(store.recent_feedback(limit=10)) == 1


def test_moves_that_are_not_user_feedback_on_the_writer_record_nothing() -> None:
    """Given a move the extension made, a move on a reader, a folder move, or a
    move out of the owned folders, When recorded, Then none is feedback."""
    store = InMemoryCorpusStore()

    results = [
        _record(store, _move(origin=MoveOrigin.EXTENSION)),
        _record(store, _move(), HostRole.READER),
        _record(store, _move(url=None)),
        _record(store, _move(to=make_path("Recipes"))),
    ]

    assert results == [None, None, None, None]
    assert store.recent_feedback(limit=10) == []


def test_an_older_move_recorded_late_leaves_the_placement_at_the_newer() -> None:
    """Given a filed bookmark the user moved twice, the newer move recorded
    first (the older one's report was answered busy and re-sent later), When
    the older move is recorded, Then both are feedback, and the placement
    stays in the folder of the newer move, where the bookmark is."""
    store = InMemoryCorpusStore()
    store.put_placement(make_placement(URL, folder=RUST))
    web = make_path("Dynomark", "Web")
    older = Move(
        node_id=NodeId("42"),
        from_path=RUST,
        to_path=ASYNC,
        origin=MoveOrigin.USER,
        observed_at=1_790_000_050_000,
        url=URL,
    )
    newer = Move(
        node_id=NodeId("42"),
        from_path=ASYNC,
        to_path=web,
        origin=MoveOrigin.USER,
        observed_at=1_790_000_060_000,
        url=URL,
    )

    _record(store, newer)
    _record(store, older)

    assert len(store.recent_feedback(limit=10)) == 2
    placement = store.get_placement(Identity(URL))
    assert placement is not None and placement.folder == web
