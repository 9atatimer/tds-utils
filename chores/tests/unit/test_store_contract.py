"""RunStorePort contract, run against the fake and the filesystem adapter
(testing-python skill section 6: contract tests pin fakes to real adapters)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from chores.adapters.fs_store import FsRunStore
from chores.domain.budget import Usage
from chores.domain.kinds import Kind
from chores.domain.run import Billing, RunRecord, RunStatus, to_ledger_row
from chores.ports.store import RunStorePort, TickMark

from ._fakes import FakeRunStore

T0 = datetime(2026, 3, 2, 10, 0)


def _record(run_id: str, *, chore: str = "c", started: datetime = T0) -> RunRecord:
    return RunRecord.pending(
        run_id=run_id,
        chore=chore,
        kind=Kind.PROMPT,
        definition_rev="abc",
        started=started,
    )


@pytest.fixture(params=["fake", "fs"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> RunStorePort:
    if request.param == "fake":
        return FakeRunStore()
    return FsRunStore(tmp_path / "state")


def test_record_round_trips_through_every_status(store: RunStorePort) -> None:
    """Given a record written at each stage, Then read_record returns the latest."""
    r = _record("c-1")
    store.write_record(r)
    running = r.start(pid=1, pgid=1, process_start=0.5)
    store.write_record(running)
    done = running.with_usage(
        Usage(tokens_in=1, tokens_out=2, usd=0.1, seconds=1.0),
        backend="b",
        model="m",
        billing=Billing.METERED,
    ).finish(RunStatus.SUCCEEDED, ended=T0 + timedelta(seconds=1), reason=None)
    store.write_record(done)
    assert store.read_record("c-1") == done
    assert store.read_record("missing") is None


def test_records_filter_by_chore_and_since_newest_first(store: RunStorePort) -> None:
    store.write_record(_record("a-1", chore="a", started=T0))
    store.write_record(_record("a-2", chore="a", started=T0 + timedelta(hours=1)))
    store.write_record(_record("b-1", chore="b", started=T0 + timedelta(hours=2)))
    assert [r.run_id for r in store.records()] == ["b-1", "a-2", "a-1"]
    assert [r.run_id for r in store.records(chore="a")] == ["a-2", "a-1"]
    assert [r.run_id for r in store.records(since=T0 + timedelta(hours=1))] == [
        "b-1",
        "a-2",
    ]


def test_artifacts_append_and_report_size(store: RunStorePort) -> None:
    store.write_record(_record("c-1"))
    size1 = store.append_artifact("c-1", "stdout.log", "hello\n")
    size2 = store.append_artifact("c-1", "stdout.log", "world\n")
    assert store.read_artifact("c-1", "stdout.log") == "hello\nworld\n"
    assert size2 > size1 and store.run_dir_bytes("c-1") == size2
    assert "stdout.log" in list(store.artifacts("c-1"))
    assert store.read_artifact("c-1", "stderr.log") == ""


def test_ledger_is_append_only_and_filters_by_since(store: RunStorePort) -> None:
    old = (
        _record("c-1", started=T0)
        .start(pid=1, pgid=1, process_start=0)
        .finish(RunStatus.FAILED, ended=T0, reason="x")
    )
    new = (
        _record("c-2", started=T0 + timedelta(days=1))
        .start(pid=1, pgid=1, process_start=0)
        .finish(RunStatus.SUCCEEDED, ended=T0 + timedelta(days=1), reason=None)
    )
    store.append_ledger(to_ledger_row(old))
    store.append_ledger(to_ledger_row(new))
    assert store.ledger_count() == 2
    assert [r["run_id"] for r in store.ledger_rows()] == ["c-1", "c-2"]
    assert [r["run_id"] for r in store.ledger_rows(since=T0 + timedelta(hours=1))] == [
        "c-2"
    ]


def test_notifications_queue_and_dismiss(store: RunStorePort) -> None:
    n1 = store.notify(at=T0, level="info", text="one", chore="c")
    n2 = store.notify(at=T0, level="alert", text="two", run_id="c-1")
    assert [n.text for n in store.notifications()] == ["one", "two"]
    assert store.dismiss(n1.id) is True
    assert [n.id for n in store.notifications()] == [n2.id]
    assert [n.id for n in store.notifications(unread_only=False)] == [n1.id, n2.id]
    assert store.dismiss("nope") is False


def test_pause_sentries(store: RunStorePort) -> None:
    assert store.paused() is None
    store.pause("flight")
    assert store.paused() == "flight"
    store.unpause()
    assert store.paused() is None
    store.pause_chore("c", "breaker")
    assert store.chore_paused("c") == "breaker" and store.chore_paused("d") is None
    store.resume_chore("c")
    assert store.chore_paused("c") is None


def test_kill_request_marker(store: RunStorePort) -> None:
    store.write_record(_record("c-1"))
    assert store.kill_requested("c-1") is False
    store.request_kill("c-1")
    assert store.kill_requested("c-1") is True


def test_tick_mark_round_trips(store: RunStorePort) -> None:
    assert store.last_tick() is None
    store.mark_tick(TickMark(at=T0, ledger_rows=3))
    assert store.last_tick() == TickMark(at=T0, ledger_rows=3)


def test_tick_lock_is_exclusive_while_held(store: RunStorePort) -> None:
    with store.tick_lock() as first:
        assert first is True
        with store.tick_lock() as second:
            assert second is False
    with store.tick_lock() as again:
        assert again is True


@pytest.mark.parametrize("make", [lambda p: FsRunStore(p / "s")])
def test_fs_state_directory_is_private(
    tmp_path: Path, make: Callable[[Path], FsRunStore]
) -> None:
    """Given the filesystem store, Then its directory is created mode 0700."""
    store = make(tmp_path)
    store.pause("x")
    assert (store.root.stat().st_mode & 0o777) == 0o700
