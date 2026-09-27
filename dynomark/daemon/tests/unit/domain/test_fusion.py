"""Hybrid ranking (DYNOMARK.DESIGN.md, Key Decisions: "fusion in the domain
over the store's two candidate lists -- testable without the store"; The
daemon, "Enrich and index"). Pure: candidate lists in, one ranked list out.
"""

from hypothesis import given
from hypothesis import strategies as st

from dynomark_daemon.domain.bookmark import Identity
from dynomark_daemon.domain.search import Candidate, fuse

_names = st.lists(st.sampled_from("abcdefghij"), unique=True, max_size=10)


def _ranked(names: list[str]) -> list[Candidate]:
    """Candidates best first, as a store returns them."""
    return [
        Candidate(Identity(name), score=1.0 - i / 20) for i, name in enumerate(names)
    ]


@given(_names, _names)
def test_fuse_keeps_every_candidate_of_either_list_once(
    text: list[str], knn: list[str]
) -> None:
    """Given two candidate lists, When fused, Then each identity of either list
    appears exactly once (a word only in captured text still reaches tier 2)."""
    fused = fuse(_ranked(text), _ranked(knn))

    assert sorted(c.identity.value for c in fused) == sorted(set(text) | set(knn))


@given(_names, _names)
def test_fuse_scores_lie_in_the_unit_interval_best_first(
    text: list[str], knn: list[str]
) -> None:
    """Given two candidate lists, When fused, Then scores are in [0, 1] and never
    rise down the list (a Hit's score)."""
    scores = [c.score for c in fuse(_ranked(text), _ranked(knn))]

    assert all(0.0 <= s <= 1.0 for s in scores)
    assert scores == sorted(scores, reverse=True)


@given(_names, _names)
def test_fuse_does_not_depend_on_which_list_is_which(
    text: list[str], knn: list[str]
) -> None:
    """Given two candidate lists, When fused in either order, Then the result is
    the same: neither signal outranks the other by position."""
    assert fuse(_ranked(text), _ranked(knn)) == fuse(_ranked(knn), _ranked(text))


def test_fuse_ranks_a_candidate_first_in_both_lists_first_with_score_one() -> None:
    """Given one identity leading both lists, When fused, Then it leads with
    score 1, and an identity in both lists outranks one at the same rank in one
    list only, and a better rank beats a worse one across lists."""
    fused = fuse(_ranked(["a", "b", "c"]), _ranked(["a", "c", "d"]))

    assert fused[0] == Candidate(Identity("a"), score=1.0)
    ranks = [c.identity.value for c in fused]
    assert ranks.index("c") < ranks.index("d")
    assert ranks.index("b") < ranks.index("d")


def test_fuse_of_two_empty_lists_is_empty() -> None:
    """Given no candidates, When fused, Then there are no hits."""
    assert fuse([], []) == []
