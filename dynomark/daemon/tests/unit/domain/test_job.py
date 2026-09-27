"""The Job and its RetryPolicy (DYNOMARK.DESIGN.md, Ubiquitous language:
"RetryPolicy -- attempts and backoff for retryable job errors")."""

from hypothesis import given
from hypothesis import strategies as st

from dynomark_daemon.domain.job import RetryPolicy

POLICY = RetryPolicy(attempts=5, initial_backoff_ms=1_000, max_backoff_ms=8_000)


def test_retry_backoff_doubles_from_the_initial_delay_up_to_the_cap() -> None:
    """Given a policy, When the delay before each retry is asked, Then it
    doubles from the initial backoff and never exceeds the cap."""
    delays = [POLICY.backoff_ms(failed) for failed in range(1, 6)]

    assert delays == [1_000, 2_000, 4_000, 8_000, 8_000]


@given(st.integers(min_value=1, max_value=10_000))
def test_retry_backoff_stays_within_initial_and_cap(failed: int) -> None:
    """Given any number of failed attempts, When the delay is asked, Then it
    lies between the initial backoff and the cap."""
    assert 1_000 <= POLICY.backoff_ms(failed) <= 8_000
