"""Retention's absence rules (Key Decisions, Retention 2026-10-16; issue
#421): values in, values out."""

from hypothesis import given
from hypothesis import strategies as st

from dynomark_daemon.domain.bookmark import Identity
from dynomark_daemon.domain.retention import plan_absences

KEEP = 1_000
IDENTITIES = st.sampled_from([Identity(f"https://{c}.example/") for c in "abcdef"])


@given(
    tracked=st.frozensets(IDENTITIES),
    present=st.frozensets(IDENTITIES),
    since=st.dictionaries(IDENTITIES, st.integers(min_value=0, max_value=3_000)),
    now=st.integers(min_value=0, max_value=3_000),
)
def test_plan_absences_drops_only_tracked_entries_gone_long_enough(
    tracked: frozenset[Identity],
    present: frozenset[Identity],
    since: dict[Identity, int],
    now: int,
) -> None:
    """Given any tracked set, tree and absences, When a sweep is planned, Then
    an entry in the tree is never dropped or newly marked gone, only a tracked
    entry absent for the whole keep is dropped, and every absence the tree no
    longer vouches for is cleared."""
    plan = plan_absences(tracked, present, since, now=now, keep_ms=KEEP)

    assert not set(plan.expired) & present
    assert not set(plan.gone) & present
    assert all(i in tracked and now - since[i] >= KEEP for i in plan.expired)
    assert set(plan.gone) == {i for i in tracked - present if i not in since}
    assert set(plan.back) == {i for i in since if i in present or i not in tracked}
