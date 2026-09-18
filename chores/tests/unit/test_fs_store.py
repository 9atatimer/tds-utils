"""FsRunStore behaviors the port contract cannot state: path safety and the
no-follow discipline of the state tree (CHORES.DESIGN.md Data Model). The
contract shared with the fake lives in test_store_contract.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chores.domain.kinds import Kind
from chores.domain.run import RunRecord

from ._harness import T0


def test_run_ids_cannot_escape_the_runs_directory(tmp_path: Path) -> None:
    from chores.adapters.fs_store import FsRunStore, InvalidRunId

    store = FsRunStore(tmp_path / "s")
    assert store.read_record("../../etc/passwd") is None
    assert store.read_artifact("../x", "stdout.log") == ""
    with pytest.raises(InvalidRunId):
        store.request_kill("../../escape")
    assert not (tmp_path / "escape").exists()


def test_notification_ids_are_unique_across_writers(tmp_path: Path) -> None:
    from chores.adapters.fs_store import FsRunStore

    a, b = FsRunStore(tmp_path / "s"), FsRunStore(tmp_path / "s")
    ids = {
        a.notify(at=T0, level="info", text="x").id,
        b.notify(at=T0, level="info", text="y").id,
    }
    assert len(ids) == 2
    assert [n.text for n in a.notifications()] == ["x", "y"]


def test_generated_run_ids_are_accepted_by_the_filesystem_store(
    tmp_path: Path,
) -> None:
    """Given a real ``new_run_id`` (uppercase T and Z in the timestamp), Then the
    store writes it: the path-safety check must not reject the ids it stores."""
    from chores.adapters.fs_store import FsRunStore
    from chores.domain.run import new_run_id

    store = FsRunStore(tmp_path / "s")
    run_id = new_run_id("brand", at=T0, suffix="ab12")
    record = RunRecord.pending(
        run_id=run_id, chore="brand", kind=Kind.PROMPT, definition_rev="r", started=T0
    )
    store.write_record(record)
    assert store.read_record(run_id) == record
    assert (tmp_path / "s" / "runs" / "brand" / run_id / "run.json").exists()


def test_chore_names_cannot_escape_the_paused_directory(tmp_path: Path) -> None:
    from chores.adapters.fs_store import FsRunStore, InvalidChoreName

    store = FsRunStore(tmp_path / "s")
    for bad in ("../../outside", "..", "a/b", "UPPER"):
        with pytest.raises(InvalidChoreName):
            store.pause_chore(bad, "x")
        with pytest.raises(InvalidChoreName):
            store.resume_chore(bad)
        with pytest.raises(InvalidChoreName):
            store.chore_paused(bad)
    assert not (tmp_path / "outside").exists()
    store.pause_chore("log-brand", "why")
    assert store.chore_paused("log-brand") == "why"


def test_records_filter_cannot_escape_the_runs_directory(tmp_path: Path) -> None:
    from chores.adapters.fs_store import FsRunStore

    outside = tmp_path / "outside" / "x"
    outside.mkdir(parents=True)
    (outside / "run.json").write_text("{}")
    store = FsRunStore(tmp_path / "s")
    assert store.records(chore="../../outside") == []
    assert store.records(chore="../outside") == []


def test_delete_run_reports_what_is_left_on_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    from chores.adapters.fs_store import FsRunStore

    store = FsRunStore(tmp_path / "s")
    store.write_record(
        RunRecord.pending(
            run_id="c-1", chore="c", kind=Kind.COMMAND, definition_rev="r", started=T0
        )
    )

    def refuse(path, *a, **kw):  # type: ignore[no-untyped-def]
        raise OSError("busy")

    monkeypatch.setattr(shutil, "rmtree", refuse)
    assert store.delete_run("c-1") is False  # the directory is still there
    assert store.read_record("c-1") is not None
    monkeypatch.undo()
    assert store.delete_run("c-1") is True and store.read_record("c-1") is None


def test_default_workspace_never_follows_a_symlink(tmp_path: Path) -> None:
    from chores.adapters.fs_store import FsWorkspaces, UnsafeWorkspace

    root = tmp_path / "data" / "workspaces"
    state = tmp_path / "state"
    state.mkdir()
    ws = FsWorkspaces(root)
    assert ws.ensure("tidy") == str(root / "tidy")
    (root / "evil").symlink_to(state)
    with pytest.raises(UnsafeWorkspace, match="symlink"):
        ws.ensure("evil")
    linked_root = tmp_path / "linked"
    linked_root.symlink_to(state)
    with pytest.raises(UnsafeWorkspace, match="symlink"):
        FsWorkspaces(linked_root).ensure("tidy")
    with pytest.raises(Exception, match="not a chore name"):
        ws.ensure("../escape")


def test_state_tree_never_follows_a_symlinked_component(tmp_path: Path) -> None:
    from chores.adapters.fs_store import FsRunStore, UnsafeStatePath

    outside = tmp_path / "outside"
    outside.mkdir()
    store = FsRunStore(tmp_path / "s")
    (store.runs / "evil").symlink_to(outside)
    record = RunRecord.pending(
        run_id="evil-20260302T100000Z-ab12",
        chore="evil",
        kind=Kind.COMMAND,
        definition_rev="r",
        started=T0,
    )
    with pytest.raises(UnsafeStatePath, match="symlink"):
        store.write_record(record)
    assert list(outside.iterdir()) == []  # nothing was written through the link
    with pytest.raises(UnsafeStatePath):
        store.read_record(record.run_id)
    (store.runs / "good").mkdir()
    (store.runs / "good" / "good-20260302T100000Z-ab12").symlink_to(outside)
    with pytest.raises(UnsafeStatePath):
        store.append_artifact("good-20260302T100000Z-ab12", "stdout.log", "x")
    assert list(outside.iterdir()) == []
    (tmp_path / "link-state").symlink_to(outside)
    with pytest.raises(UnsafeStatePath):
        FsRunStore(tmp_path / "link-state")


def test_no_state_file_is_ever_read_or_written_through_a_symlink(
    tmp_path: Path,
) -> None:
    from chores.adapters.fs_store import (
        FsRunStore,
        InvalidArtifactName,
        UnsafeStatePath,
    )

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "run.json").write_text("{}")
    store = FsRunStore(tmp_path / "s")
    run_id = "tidy-20260302T100000Z-ab12"
    record = RunRecord.pending(
        run_id=run_id, chore="tidy", kind=Kind.COMMAND, definition_rev="r", started=T0
    )
    store.write_record(record)
    run_dir = store.runs / "tidy" / run_id
    # enumeration never follows a symlinked chore dir, run dir or record
    (store.runs / "linked-chore").symlink_to(outside)
    (store.runs / "tidy" / "linked-run").symlink_to(outside)
    (store.runs / "tidy" / "tidy-20260302T110000Z-ab12").mkdir()
    (store.runs / "tidy" / "tidy-20260302T110000Z-ab12" / "run.json").symlink_to(
        outside / "run.json"
    )
    assert [r.run_id for r in store.records()] == [run_id]
    # artifacts, the ledger and the sentries are written no-follow
    target = outside / "leak.log"
    (run_dir / "stdout.log").symlink_to(target)
    with pytest.raises(UnsafeStatePath):
        store.append_artifact(run_id, "stdout.log", "secret\n")
    assert not target.exists()
    with pytest.raises(UnsafeStatePath):
        store.read_artifact(run_id, "stdout.log")
    with pytest.raises(InvalidArtifactName):
        store.append_artifact(run_id, "../escape", "x")
    (store.root / "ledger.ndjson").symlink_to(outside / "ledger")
    with pytest.raises(UnsafeStatePath):
        store.append_ledger({"a": 1})
    assert not (outside / "ledger").exists()
    (store.root / "PAUSED").symlink_to(outside / "paused")
    with pytest.raises(UnsafeStatePath):
        store.pause("x")
    with pytest.raises(UnsafeStatePath):
        store.paused()
    assert store.run_dir_bytes(run_id) > 0  # counts real files only


def test_fs_chore_lock_lives_in_the_chore_dir_and_is_no_follow(tmp_path: Path) -> None:
    from chores.adapters.fs_store import FsRunStore, UnsafeStatePath

    store = FsRunStore(tmp_path / "s")
    with store.chore_lock("tidy"):
        assert (store.runs / "tidy" / "admission.lock").is_file()
    outside = tmp_path / "outside"
    outside.mkdir()
    (store.runs / "evil").mkdir()
    (store.runs / "evil" / "admission.lock").symlink_to(outside / "lock")
    with pytest.raises(UnsafeStatePath):
        with store.chore_lock("evil"):
            pass
    assert not (outside / "lock").exists()


def test_read_nofollow_is_one_descriptor(tmp_path: Path) -> None:
    from chores.adapters.fs_store import UnsafeStatePath, read_nofollow

    assert read_nofollow(tmp_path / "missing") is None
    (tmp_path / "f").write_text("x")
    assert read_nofollow(tmp_path / "f") == "x"
    (tmp_path / "d").mkdir()
    assert read_nofollow(tmp_path / "d") is None  # not a regular file
    (tmp_path / "l").symlink_to(tmp_path / "f")
    with pytest.raises(UnsafeStatePath):
        read_nofollow(tmp_path / "l")  # ELOOP from the kernel, never followed


def test_kill_marker_is_read_no_follow(tmp_path: Path) -> None:
    from chores.adapters.fs_store import FsRunStore, UnsafeStatePath

    store = FsRunStore(tmp_path / "s")
    run_id = "tidy-20260302T100000Z-ab12"
    store.write_record(
        RunRecord.pending(
            run_id=run_id,
            chore="tidy",
            kind=Kind.COMMAND,
            definition_rev="r",
            started=T0,
        )
    )
    assert store.kill_requested(run_id) is False
    (store.runs / "tidy" / run_id / "KILL").symlink_to(tmp_path / "s" / "ledger.ndjson")
    with pytest.raises(UnsafeStatePath):
        store.kill_requested(run_id)  # a planted link never counts as a kill


def test_pause_sentries_refuse_a_symlinked_parent(tmp_path: Path) -> None:
    """The per-chore sentry's parents are checked at every use: a `paused.d`
    dir swapped for a symlink after construction is refused by pause, read
    and resume alike, and nothing lands outside the state tree."""
    from chores.adapters.fs_store import FsRunStore, UnsafeStatePath

    store = FsRunStore(tmp_path / "state")
    store.pause_chore("tidy", "before")
    assert store.chore_paused("tidy") == "before"
    outside = tmp_path / "outside"
    outside.mkdir()
    paused = tmp_path / "state" / "paused.d"
    (paused / "tidy").unlink()
    paused.rmdir()
    paused.symlink_to(outside)
    with pytest.raises(UnsafeStatePath, match="symlink"):
        store.pause_chore("tidy", "after")
    with pytest.raises(UnsafeStatePath, match="symlink"):
        store.chore_paused("tidy")
    with pytest.raises(UnsafeStatePath, match="symlink"):
        store.resume_chore("tidy")
    assert list(outside.iterdir()) == []


def test_global_and_per_chore_sentries_do_not_collide_case_insensitively(
    tmp_path: Path,
) -> None:
    """The default macOS filesystem folds case: a `paused/` dir and the
    `PAUSED` file would be the same entry. The state root must never carry
    two names that differ only by case (found by the macOS CI leg)."""
    from chores.adapters.fs_store import FsRunStore

    store = FsRunStore(tmp_path / "state")
    store.pause("flight")
    store.pause_chore("tidy", "wip")
    assert store.paused() == "flight" and store.chore_paused("tidy") == "wip"
    names = [p.name for p in (tmp_path / "state").iterdir()]
    assert len({n.lower() for n in names}) == len(names), names


def test_torn_ledger_tail_is_skipped_and_corruption_is_named(tmp_path: Path) -> None:
    """An append cut off mid-row (full disk, dead process) leaves a torn final
    line: readers skip it, because the row it was going to be never landed. An
    undecodable row anywhere else is corruption and raises CorruptState naming
    the file and line."""
    from chores.adapters.fs_store import CorruptState, FsRunStore

    store = FsRunStore(tmp_path / "state")
    store.append_ledger({"run_id": "a", "started": T0.isoformat()})
    store.append_ledger({"run_id": "b", "started": T0.isoformat()})
    ledger = tmp_path / "state" / "ledger.ndjson"
    with ledger.open("a") as fh:
        fh.write('{"run_id": "c", "star')  # torn: no newline, no closing brace
    assert store.ledger_count() == 2
    assert [r["run_id"] for r in store.ledger_rows()] == ["a", "b"]
    ledger.write_text('{"run_id": "a"}\nnot json\n{"run_id": "b"}\n')
    with pytest.raises(CorruptState, match="ledger.ndjson:2"):
        store.ledger_count()
