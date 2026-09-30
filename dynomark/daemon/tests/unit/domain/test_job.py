"""The Job and its RetryPolicy (DYNOMARK.DESIGN.md, Ubiquitous language:
"RetryPolicy -- attempts and backoff for retryable job errors")."""

import itertools

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dynomark_daemon.domain.job import (
    TRANSITIONS,
    IllegalTransition,
    JobState,
    RetryPolicy,
)
from tests._factories import make_job

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


# --- The State Machine table (DYNOMARK.DESIGN.md, State Machine) ---

QU, CA, EN, PL, FI, IN, FA = (
    JobState.QUEUED,
    JobState.CAPTURING,
    JobState.ENRICHED,
    JobState.PLACED,
    JobState.FILED,
    JobState.INDEXED,
    JobState.FAILED,
)
DESIGN_TRANSITIONS = {
    (QU, CA),  # job picked up
    (CA, EN),  # capture resolved and entry enriched
    (EN, IN),  # entry indexed (reader)
    (EN, PL),  # placement recorded (writer)
    (PL, FI),  # APPLIED receipt
    (QU, FA),  # retries exhausted, or PARTIAL / REJECTED receipt
    (CA, FA),
    (EN, FA),
    (PL, FA),
    (FA, QU),  # user retries
}


@pytest.mark.parametrize(
    ("source", "target"), list(itertools.product(JobState, JobState))
)
def test_job_moves_exactly_along_the_design_state_machine(
    source: JobState, target: JobState
) -> None:
    """Given a job in any state, When moved to any state, Then the move happens
    (with a new seq) exactly when the design's State Machine table lists it,
    and raises IllegalTransition otherwise -- FILED and INDEXED are terminal."""
    job = make_job(state=source)

    if (source, target) in DESIGN_TRANSITIONS:
        moved = job.moved_to(target, at=5)
        assert (moved.state, moved.seq, moved.updated_at) == (target, job.seq + 1, 5)
    else:
        with pytest.raises(IllegalTransition):
            job.moved_to(target, at=5)


def test_state_machine_table_is_the_design_table() -> None:
    """Given the domain's transition table, When compared with the design's,
    Then they are the same set (no transition added, none missing)."""
    assert set(TRANSITIONS) == DESIGN_TRANSITIONS


def test_named_job_changes_follow_the_state_machine() -> None:
    """Given a job FILED (terminal), When any named change would move it, Then it
    raises IllegalTransition (every use case goes through the table)."""
    filed = make_job(state=JobState.FILED)

    for change in (filed.picked_up, filed.placed, filed.indexed, filed.filed):
        with pytest.raises(IllegalTransition):
            change(at=1)
    with pytest.raises(IllegalTransition):
        filed.failed("late receipt", at=1)
