"""Behaviors rows: An entry is placed; Placement respects a lock
(DYNOMARK.DESIGN.md, Behaviors and Interfaces; Placement policy) --
``place(entry, outline, feedback, role, *, store, embedding, completion)
-> Placement or NotWriter``; and Goal 3: "place is a pure function of
(entry, neighbours, outline, feedback, completion output)".
"""

from dynomark_daemon.app.place import place
from dynomark_daemon.domain.bookmark import Identity
from dynomark_daemon.domain.placement import FolderChoice, Placement
from dynomark_daemon.domain.roles import HostRole
from dynomark_daemon.domain.tree import FolderPath, TreeOutline
from dynomark_daemon.testing.clock import FakeClock
from dynomark_daemon.testing.completion import ChooseFolderCall, ScriptedCompletion
from dynomark_daemon.testing.embedding import HashingEmbedding
from dynomark_daemon.testing.store import InMemoryCorpusStore
from tests._factories import (
    make_entry,
    make_feedback,
    make_outline,
    make_outline_folder,
    make_path,
    make_placement,
)

RUST = make_path("Dynomark", "Rust")
GO = make_path("Dynomark", "Go")
NEW = make_entry("https://docs.rs/tokio", title="tokio docs", vector=(1.0, 0.0))
NEIGHBOURS = (
    ("https://tokio.rs/", (0.99, 0.01), RUST),
    ("https://async.rs/", (0.98, 0.02), RUST),
    ("https://smol.rs/", (0.97, 0.03), RUST),
)


def _store_with_neighbours(
    neighbours: tuple[tuple[str, tuple[float, float], FolderPath], ...] = NEIGHBOURS,
) -> InMemoryCorpusStore:
    store = InMemoryCorpusStore()
    for url, vector, folder in neighbours:
        store.put_entry(make_entry(url, title=url, vector=vector))
        store.put_placement(make_placement(url, folder=folder))
    store.put_entry(make_entry("https://unplaced.example/", vector=(1.0, 0.0)))
    store.put_entry(NEW)
    return store


def _place(
    store: InMemoryCorpusStore,
    outline: TreeOutline,
    completion: ScriptedCompletion,
) -> Placement:
    placement = place(
        NEW,
        outline,
        [make_feedback("fb-1")],
        HostRole.WRITER,
        store=store,
        embedding=HashingEmbedding(),
        completion=completion,
        clock=FakeClock(start_ms=7_000),
    )
    assert isinstance(placement, Placement)
    return placement


def test_place_names_the_folder_of_three_neighbours_and_lists_them() -> None:
    """Given three placed neighbours in one folder and a fake completion echoing
    it, When placed, Then the placement names that folder, its reason lists the
    neighbours and the feedback used, and it is recorded."""
    store = _store_with_neighbours()
    completion = ScriptedCompletion(
        choose_folder=[FolderChoice(folder=RUST, rationale="like its neighbours")]
    )
    outline = make_outline(make_outline_folder("Dynomark", "Rust"))

    placement = _place(store, outline, completion)

    assert placement.folder == RUST
    assert [n.identity for n in placement.reason.neighbours] == [
        Identity(url) for url, _, _ in NEIGHBOURS
    ]
    assert {n.path for n in placement.reason.neighbours} == {RUST}
    assert placement.reason.feedback_ids == (make_feedback("fb-1").feedback_id,)
    assert placement.reason.model_id == "fake:scripted"
    assert store.get_placement(NEW.identity) == placement
    (call,) = completion.calls
    assert isinstance(call, ChooseFolderCall)
    assert call.neighbours == placement.reason.neighbours


def test_place_twice_with_one_completion_answer_gives_one_placement() -> None:
    """Given a fake completion returning a fixed answer, When the entry is placed
    twice, Then both placements are equal (Goal 3)."""
    answer = FolderChoice(folder=RUST, rationale="like its neighbours")
    store = _store_with_neighbours()
    outline = make_outline(make_outline_folder("Dynomark", "Rust"))

    first = _place(store, outline, ScriptedCompletion(choose_folder=[answer]))
    second = _place(store, outline, ScriptedCompletion(choose_folder=[answer]))

    assert first == second


def test_place_when_the_completion_names_a_locked_folder_picks_a_sibling() -> None:
    """Given the fake completion names a locked folder, When placed, Then the
    result is a sibling, never inside the locked folder."""
    neighbours = (*NEIGHBOURS[:2], ("https://smol.rs/", (0.97, 0.03), GO))
    store = _store_with_neighbours(neighbours)
    outline = make_outline(
        make_outline_folder("Dynomark", "Rust", locked=True),
        make_outline_folder("Dynomark", "Go"),
    )

    placement = _place(
        store,
        outline,
        ScriptedCompletion(choose_folder=[FolderChoice(folder=RUST, rationale="r")]),
    )

    assert placement.folder == GO


def test_place_never_puts_a_new_leaf_inside_a_locked_folder() -> None:
    """Given the fake completion proposes a new leaf under a locked folder and
    no neighbour sits in an unlocked one, When placed, Then the result is not
    inside the locked folder."""
    store = _store_with_neighbours()
    outline = make_outline(make_outline_folder("Dynomark", "Rust", locked=True))
    leaf = make_path("Dynomark", "Rust", "Async")

    placement = _place(
        store,
        outline,
        ScriptedCompletion(choose_folder=[FolderChoice(folder=leaf, rationale="r")]),
    )

    assert placement.folder.names[:2] != ("Dynomark", "Rust")
    assert placement.folder == make_path("Dynomark")


def test_place_a_proposed_new_leaf_under_an_existing_folder() -> None:
    """Given the fake completion proposes one new leaf under an existing owned
    folder, When placed, Then the placement names the new leaf."""
    store = _store_with_neighbours()
    outline = make_outline(make_outline_folder("Dynomark", "Rust"))
    leaf = make_path("Dynomark", "Rust", "Async")

    placement = _place(
        store,
        outline,
        ScriptedCompletion(choose_folder=[FolderChoice(folder=leaf, rationale="r")]),
    )

    assert placement.folder == leaf


def test_place_a_new_leaf_colliding_with_an_existing_name_is_that_folder() -> None:
    """Given a proposed leaf whose name collides with an existing folder at the
    same level (case and surrounding space aside), When placed, Then it
    resolves to the existing folder (Placement policy, rule 3)."""
    store = _store_with_neighbours()
    outline = make_outline(make_outline_folder("Dynomark", "Rust"))
    variant = make_path("Dynomark", " rust ")

    placement = _place(
        store,
        outline,
        ScriptedCompletion(choose_folder=[FolderChoice(folder=variant, rationale="")]),
    )

    assert placement.folder == RUST


def test_place_outside_the_dynomark_folder_falls_back_to_the_neighbours() -> None:
    """Given the fake completion names a folder outside the owned tree, When
    placed, Then the placement stays inside Dynomark, where the neighbours are."""
    store = _store_with_neighbours()
    outline = make_outline(make_outline_folder("Dynomark", "Rust"))
    outside = make_path("Recipes")

    placement = _place(
        store,
        outline,
        ScriptedCompletion(choose_folder=[FolderChoice(folder=outside, rationale="")]),
    )

    assert placement.folder == RUST
