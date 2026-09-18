"""RunRecord state machine and ledger row (CHORES.DESIGN.md State Machine)."""

from __future__ import annotations

from datetime import datetime

import pytest

from chores.domain.budget import Usage
from chores.domain.chore import Kind
from chores.domain.run import (
    Billing,
    IllegalTransition,
    RunRecord,
    RunStatus,
    new_run_id,
    to_ledger_row,
)

T0 = datetime(2026, 3, 2, 10, 0)


def pending() -> RunRecord:
    return RunRecord.pending(
        run_id="brand-20260302T100000Z-ab12",
        chore="brand",
        kind=Kind.PROMPT,
        definition_rev="abc123",
        started=T0,
    )


def test_new_run_id_embeds_chore_and_utc_stamp() -> None:
    """Given a chore and instant, Then the id is <chore>-<UTC stamp>-<suffix>."""
    assert new_run_id("brand", at=T0, suffix="ab12") == "brand-20260302T100000Z-ab12"


def test_pending_to_running_records_process_identity() -> None:
    """Given PENDING, When the process starts, Then pid, pgid, start time are kept."""
    r = pending().start(pid=42, pgid=42, process_start=1234.5)
    assert r.status is RunStatus.RUNNING
    assert (r.pid, r.pgid, r.process_start) == (42, 42, 1234.5)


@pytest.mark.parametrize(
    "terminal",
    [
        RunStatus.SUCCEEDED,
        RunStatus.FAILED,
        RunStatus.TIMED_OUT,
        RunStatus.BUDGET_EXCEEDED,
        RunStatus.KILLED,
        RunStatus.OFFLINE,
        RunStatus.INTERRUPTED,
    ],
)
def test_running_reaches_every_terminal_status(terminal: RunStatus) -> None:
    """Given RUNNING, When finished with a terminal status, Then ended is set."""
    r = pending().start(pid=1, pgid=1, process_start=0.0)
    done = r.finish(
        terminal, ended=T0, reason=None if terminal is RunStatus.SUCCEEDED else "why"
    )
    assert done.status is terminal and done.ended == T0 and done.pid is None


def test_non_success_requires_a_reason() -> None:
    """Given a failure without a reason, Then the transition is refused."""
    r = pending().start(pid=1, pgid=1, process_start=0.0)
    with pytest.raises(IllegalTransition):
        r.finish(RunStatus.FAILED, ended=T0, reason=None)


def test_pending_can_only_run_or_be_interrupted() -> None:
    """Given PENDING, Then SUCCEEDED is illegal but INTERRUPTED is legal."""
    with pytest.raises(IllegalTransition):
        pending().finish(RunStatus.SUCCEEDED, ended=T0, reason=None)
    assert (
        pending().finish(RunStatus.INTERRUPTED, ended=T0, reason="never started").status
        is RunStatus.INTERRUPTED
    )


def test_terminal_is_final() -> None:
    """Given a terminal record, Then no further transition is legal."""
    done = (
        pending()
        .start(pid=1, pgid=1, process_start=0.0)
        .finish(RunStatus.SUCCEEDED, ended=T0, reason=None)
    )
    with pytest.raises(IllegalTransition):
        done.finish(RunStatus.FAILED, ended=T0, reason="x")
    with pytest.raises(IllegalTransition):
        done.start(pid=2, pgid=2, process_start=0.0)


def test_ledger_row_is_flat_and_schema_keyed() -> None:
    """Given a terminal record with usage, Then the row is flat, schema-keyed, and
    carries no prompt content."""
    done = (
        pending()
        .start(pid=1, pgid=1, process_start=0.0)
        .with_usage(
            Usage(tokens_in=10, tokens_out=20, usd=0.01, seconds=3.0),
            backend="gw",
            model="m",
            billing=Billing.METERED,
        )
        .finish(RunStatus.SUCCEEDED, ended=T0, reason=None)
    )
    row = to_ledger_row(done)
    assert row["schema"] == "chores/v1"
    assert row["status"] == "SUCCEEDED"
    assert row["tokens_in"] == 10 and row["usd"] == 0.01 and row["billing"] == "metered"
    assert all(not isinstance(v, dict | list) for v in row.values())
    assert "body" not in row and "prompt" not in row


def test_tick_written_outcome_is_terminal_on_creation() -> None:
    """Given a MISSED outcome, Then it is created terminal with its reason."""
    r = RunRecord.outcome(
        run_id="brand-x",
        chore="brand",
        kind=Kind.PROMPT,
        definition_rev="abc",
        status=RunStatus.MISSED,
        reason="3 slots older than grace",
        at=T0,
    )
    assert r.status is RunStatus.MISSED and r.ended == T0
    with pytest.raises(IllegalTransition):
        r.start(pid=1, pgid=1, process_start=0.0)
