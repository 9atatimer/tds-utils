"""FsRunStore -- the state directory as a RunStorePort (CHORES.DESIGN.md Data
Model: ``runs/<chore>/<run-id>/``, ``ledger.ndjson``, ``notifications.ndjson``,
``last_tick``, ``PAUSED``, ``paused.d/<chore>``, ``tick.lock``; mode 0700).
The per-chore sentry dir is ``paused.d``, not ``paused``: the default macOS
filesystem is case-insensitive, and ``paused`` would BE the ``PAUSED`` file.

Records are JSON documents rewritten on every transition; artifacts and the
two NDJSON files are append-only; the tick lock is an OS-held ``flock`` that
dies with the process.
"""

from __future__ import annotations

import errno
import fcntl
import json
import os
import re
import secrets
import shutil
import stat
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime
from pathlib import Path

from chores.domain.budget import Usage
from chores.domain.errors import InfrastructureError
from chores.domain.kinds import Kind
from chores.domain.run import Billing, RunRecord, RunStatus
from chores.ports.store import ARTIFACTS, Artifact, Notification, TickMark

# A run id is ``<chore>-<yyyymmddThhmmssZ>-<suffix>`` (domain ``new_run_id``):
# the timestamp carries an uppercase T and Z, so the class is case-insensitive.
# Chore names are the domain's ``[a-z0-9]+(-[a-z0-9]+)*``. Both reach here from
# CLI arguments, and both are used as path components.
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9]+(-[A-Za-z0-9]+)*$")
_CHORE_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class InvalidRunId(InfrastructureError):
    """A run id that is not a single path-safe segment (CLI input reaches here)."""


class InvalidChoreName(InfrastructureError):
    """A chore name that is not a single path-safe segment (CLI input reaches here)."""


class UnsafeWorkspace(InfrastructureError):
    """The default workspace is a symlink or resolves outside the data root."""


class UnsafeStatePath(InfrastructureError):
    """A path inside the 0700 state tree is a symlink: a pre-planted link
    could redirect records, artifacts, the ledger or a sentry elsewhere (or
    read foreign content back in), so it is refused rather than followed.
    Every open in the tree goes through the no-follow helpers below."""


class CorruptState(InfrastructureError):
    """An NDJSON state file has an undecodable row that is not a torn tail:
    the file needs a human, and every reader says so by name instead of
    raising a bare decode error."""


class InvalidArtifactName(InfrastructureError):
    """An artifact name outside the fixed set (never a caller-chosen path)."""


def check_artifact_name(name: str) -> str:
    if name not in ARTIFACTS:
        raise InvalidArtifactName(f"not an artifact: {name!r}")
    return name


def write_nofollow(path: Path, text: str, *, append: bool = False) -> None:
    """Create or append to ``path`` without ever following a symlink at
    ``path`` itself (O_NOFOLLOW); the parent was already checked."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW
    flags |= os.O_APPEND if append else os.O_TRUNC
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as e:
        if path.is_symlink():
            raise UnsafeStatePath(f"{path} is a symlink; refusing to write") from e
        raise
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)


def read_nofollow(path: Path) -> str | None:
    """The file's text, None when absent. One O_NOFOLLOW open and one read
    on that descriptor: a symlink is refused by the kernel (ELOOP), never
    followed, and nothing can be swapped in between a check and the read."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    except OSError as e:
        if e.errno == errno.ELOOP or path.is_symlink():
            raise UnsafeStatePath(f"{path} is a symlink; refusing to read") from e
        raise
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        return None  # a directory or device is "absent" as a text file
    with os.fdopen(fd, "r", encoding="utf-8") as fh:
        return fh.read()


def _is_real_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def check_run_id(run_id: str) -> str:
    if not _RUN_ID_RE.match(run_id):
        raise InvalidRunId(f"not a run id: {run_id!r}")
    return run_id


def check_chore_name(name: str) -> str:
    if not _CHORE_NAME_RE.match(name):
        raise InvalidChoreName(f"not a chore name: {name!r}")
    return name


# --- serialization -----------------------------------------------------------


def record_to_json(record: RunRecord) -> dict[str, object]:
    usage = record.usage
    return {
        "run_id": record.run_id,
        "chore": record.chore,
        "kind": record.kind.value,
        "definition_rev": record.definition_rev,
        "status": record.status.value,
        "reason": record.reason,
        "started": record.started.isoformat(),
        "ended": record.ended.isoformat() if record.ended else None,
        "pid": record.pid,
        "pgid": record.pgid,
        "process_start": record.process_start,
        "backend": record.backend,
        "model": record.model,
        "billing": record.billing.value if record.billing else None,
        "usage": None
        if usage is None
        else {
            "tokens_in": usage.tokens_in,
            "tokens_out": usage.tokens_out,
            "seconds": usage.seconds,
            "usd": usage.usd,
            "turns": usage.turns,
            "cpu_seconds": usage.cpu_seconds,
            "disk_bytes": usage.disk_bytes,
        },
        "exit_code": record.exit_code,
        "truncated": record.truncated,
    }


def record_from_json(data: Mapping[str, object]) -> RunRecord:
    raw_usage = data.get("usage")
    usage = None
    if isinstance(raw_usage, Mapping):
        usage = Usage(
            tokens_in=int(str(raw_usage["tokens_in"])),
            tokens_out=int(str(raw_usage["tokens_out"])),
            seconds=float(str(raw_usage["seconds"])),
            usd=_opt_float(raw_usage.get("usd")),
            turns=_opt_int(raw_usage.get("turns")),
            cpu_seconds=float(str(raw_usage.get("cpu_seconds", 0.0))),
            disk_bytes=int(str(raw_usage.get("disk_bytes", 0))),
        )
    billing = data.get("billing")
    return RunRecord(
        run_id=str(data["run_id"]),
        chore=str(data["chore"]),
        kind=Kind(str(data["kind"])),
        definition_rev=str(data["definition_rev"]),
        status=RunStatus(str(data["status"])),
        started=datetime.fromisoformat(str(data["started"])),
        reason=_opt_str(data.get("reason")),
        ended=_opt_dt(data.get("ended")),
        pid=_opt_int(data.get("pid")),
        pgid=_opt_int(data.get("pgid")),
        process_start=_opt_float(data.get("process_start")),
        backend=_opt_str(data.get("backend")),
        model=_opt_str(data.get("model")),
        billing=Billing(str(billing)) if billing else None,
        usage=usage,
        exit_code=_opt_int(data.get("exit_code")),
        truncated=bool(data.get("truncated", False)),
    )


def _opt_str(v: object) -> str | None:
    return None if v is None else str(v)


def _opt_int(v: object) -> int | None:
    return None if v is None else int(str(v))


def _opt_float(v: object) -> float | None:
    return None if v is None else float(str(v))


def _opt_dt(v: object) -> datetime | None:
    return None if v is None else datetime.fromisoformat(str(v))


# --- the adapter -------------------------------------------------------------


class FsRunStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.runs = root / "runs"
        self._ensure_private(root)
        self._ensure_private(self.runs)
        self._ensure_private(root / "paused.d")

    # --- helpers ---

    @staticmethod
    def _ensure_private(path: Path) -> None:
        if path.is_symlink():
            raise UnsafeStatePath(f"{path} is a symlink; refusing to use it")
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path, 0o700, follow_symlinks=False)

    @staticmethod
    def _real_dir(path: Path) -> bool:
        """A directory that is not reached through a symlink at this level."""
        return path.is_dir() and not path.is_symlink()

    def _run_dir(self, run_id: str) -> Path:
        check_run_id(run_id)
        chore = run_id.rsplit("-", 2)[0]
        path = self.runs / chore / run_id
        for component in (self.runs, path.parent, path):
            if component.is_symlink():
                raise UnsafeStatePath(f"{component} is a symlink; refusing to use it")
        return path

    def _find_run_dir(self, run_id: str) -> Path | None:
        if not _RUN_ID_RE.match(run_id):
            return None
        direct = self._run_dir(run_id)  # raises on a symlinked component
        if self._real_dir(direct):
            return direct
        for candidate in self.runs.glob(f"*/{run_id}"):
            if self._real_dir(candidate) and self._real_dir(candidate.parent):
                return candidate
        return None

    @staticmethod
    def _append(path: Path, text: str) -> None:
        write_nofollow(path, text, append=True)

    @staticmethod
    def _read_ndjson(path: Path) -> list[dict[str, object]]:
        """Every decodable row. A torn final line (an append cut off by a
        full disk or a dead process, so no trailing newline) is skipped: the
        row it was going to be never landed. An undecodable line anywhere
        else, or a torn line that IS newline-terminated, is corruption and
        raises CorruptState naming the file and line."""
        text = read_nofollow(path)
        if text is None:
            return []
        rows: list[dict[str, object]] = []
        lines = text.split("\n")
        for number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except ValueError as e:
                if number == len(lines):  # last piece, no newline after it
                    break
                raise CorruptState(f"{path}:{number}: undecodable row: {e}") from e
        return rows

    # --- records ---

    def write_record(self, record: RunRecord) -> None:
        run_dir = self._run_dir(record.run_id)
        self._ensure_private(run_dir.parent)
        self._ensure_private(run_dir)
        with self._record_lock(run_dir):
            self._write_json(run_dir, record)

    @staticmethod
    def _write_json(run_dir: Path, record: RunRecord) -> None:
        tmp = run_dir / "run.json.tmp"
        write_nofollow(tmp, json.dumps(record_to_json(record), indent=1))
        os.replace(tmp, run_dir / "run.json")  # replaces a planted link itself

    @contextmanager
    def _record_lock(self, run_dir: Path) -> Iterator[None]:
        """Blocking per-run lock: ``transition`` reads and writes under it, and
        every ``write_record`` takes it, so a check-and-set cannot interleave
        with a runner's own write."""
        lock = run_dir / "record.lock"
        if lock.is_symlink():
            raise UnsafeStatePath(f"{lock} is a symlink; refusing to lock")
        fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "a+") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    def transition(
        self,
        run_id: str,
        *,
        expected: RunStatus,
        then: Callable[[RunRecord], RunRecord],
    ) -> RunRecord | None:
        run_dir = self._find_run_dir(run_id)
        if run_dir is None:
            return None
        with self._record_lock(run_dir):
            current = self.read_record(run_id)
            if current is None or current.status is not expected:
                return None
            done = then(current)
            self._write_json(run_dir, done)
            return done

    def read_record(self, run_id: str) -> RunRecord | None:
        run_dir = self._find_run_dir(run_id)
        if run_dir is None:
            return None
        text = read_nofollow(run_dir / "run.json")
        return None if text is None else record_from_json(json.loads(text))

    def records(
        self, *, chore: str | None = None, since: datetime | None = None
    ) -> Sequence[RunRecord]:
        out: list[RunRecord] = []
        if chore is not None and not _RUN_ID_RE.match(chore):
            return []  # not a path segment: nothing can be filed under it
        chore_dirs = [self.runs / chore] if chore else sorted(self.runs.iterdir())
        for chore_dir in chore_dirs:
            if not self._real_dir(chore_dir):
                continue  # a symlinked chore dir is never followed
            for run_json in chore_dir.glob("*/run.json"):
                if not self._real_dir(run_json.parent):
                    continue  # nor a symlinked run dir
                try:
                    text = read_nofollow(run_json)  # nor a symlinked record
                except UnsafeStatePath:
                    continue
                if text is None:
                    continue
                record = record_from_json(json.loads(text))
                if since is None or record.started >= since:
                    out.append(record)
        return sorted(out, key=lambda r: (r.started, r.run_id), reverse=True)

    # --- artifacts ---

    def append_artifact(self, run_id: str, name: Artifact, text: str) -> int:
        check_artifact_name(name)
        run_dir = self._run_dir(run_id)
        self._ensure_private(run_dir)
        self._append(run_dir / name, text)
        return self.run_dir_bytes(run_id)

    def read_artifact(self, run_id: str, name: Artifact) -> str:
        check_artifact_name(name)
        run_dir = self._find_run_dir(run_id)
        if run_dir is None:
            return ""
        return read_nofollow(run_dir / name) or ""

    def run_dir_bytes(self, run_id: str) -> int:
        run_dir = self._find_run_dir(run_id)
        if run_dir is None:
            return 0
        return sum(
            p.lstat().st_size
            for p in run_dir.iterdir()
            if p.is_file() and not p.is_symlink()
        )

    def artifacts(self, run_id: str) -> Iterator[Artifact]:
        run_dir = self._find_run_dir(run_id)
        if run_dir is None:
            return iter(())
        return (name for name in ARTIFACTS if _is_real_file(run_dir / name))

    def delete_run(self, run_id: str) -> bool:
        run_dir = self._find_run_dir(run_id)
        if run_dir is None:
            return False
        try:
            shutil.rmtree(run_dir)
        except OSError:
            pass  # reported below by what is actually left on disk
        return not run_dir.exists()

    # --- kill requests ---

    def request_kill(self, run_id: str) -> None:
        run_dir = self._run_dir(run_id)
        self._ensure_private(run_dir)
        write_nofollow(run_dir / "KILL", "")

    def kill_requested(self, run_id: str) -> bool:
        run_dir = self._find_run_dir(run_id)
        return run_dir is not None and read_nofollow(run_dir / "KILL") is not None

    # --- ledger ---

    def append_ledger(self, row: Mapping[str, object]) -> None:
        self._append(self.root / "ledger.ndjson", json.dumps(dict(row)) + "\n")

    def ledger_rows(
        self, *, since: datetime | None = None
    ) -> Sequence[Mapping[str, object]]:
        rows = self._read_ndjson(self.root / "ledger.ndjson")
        if since is None:
            return rows
        return [r for r in rows if datetime.fromisoformat(str(r["started"])) >= since]

    def ledger_count(self) -> int:
        return len(self._read_ndjson(self.root / "ledger.ndjson"))

    # --- notifications ---

    def notify(
        self,
        *,
        at: datetime,
        level: str,
        text: str,
        run_id: str | None = None,
        chore: str | None = None,
    ) -> Notification:
        n = Notification(
            id=f"n{at.strftime('%Y%m%dT%H%M%S')}-{secrets.token_hex(2)}",
            ts=at,
            run_id=run_id,
            chore=chore,
            level=level,
            text=text,
            read=False,
        )
        row = {
            "id": n.id,
            "ts": at.isoformat(),
            "run_id": run_id,
            "chore": chore,
            "level": level,
            "text": text,
        }
        self._append(self.root / "notifications.ndjson", json.dumps(row) + "\n")
        return n

    def notifications(self, *, unread_only: bool = True) -> Sequence[Notification]:
        rows = self._read_ndjson(self.root / "notifications.ndjson")
        dismissed = {str(r["dismiss"]) for r in rows if "dismiss" in r}
        out: list[Notification] = []
        for r in rows:
            if "text" not in r:
                continue
            read = str(r["id"]) in dismissed
            if unread_only and read:
                continue
            out.append(
                Notification(
                    id=str(r["id"]),
                    ts=datetime.fromisoformat(str(r["ts"])),
                    run_id=_opt_str(r.get("run_id")),
                    chore=_opt_str(r.get("chore")),
                    level=str(r["level"]),
                    text=str(r["text"]),
                    read=read,
                )
            )
        return out

    def dismiss(self, notification_id: str) -> bool:
        known = {n.id for n in self.notifications(unread_only=False)}
        if notification_id not in known:
            return False
        self._append(
            self.root / "notifications.ndjson",
            json.dumps({"dismiss": notification_id}) + "\n",
        )
        return True

    # --- pause sentries ---

    def pause(self, reason: str) -> None:
        write_nofollow(self.root / "PAUSED", reason)

    def unpause(self) -> None:
        (self.root / "PAUSED").unlink(missing_ok=True)

    def paused(self) -> str | None:
        text = read_nofollow(self.root / "PAUSED")
        if text is None:
            return None
        return text.strip() or "(no reason recorded)"

    def _sentry(self, name: str) -> Path:
        """The per-chore pause sentry. Its parents are checked at every use,
        like a run dir's components: a ``paused.d`` dir swapped for a symlink
        after construction is refused, never followed."""
        paused = self.root / "paused.d"
        for component in (self.root, paused):
            if component.is_symlink():
                raise UnsafeStatePath(f"{component} is a symlink; refusing to use it")
        return paused / check_chore_name(name)

    def pause_chore(self, name: str, reason: str) -> None:
        write_nofollow(self._sentry(name), reason)

    def resume_chore(self, name: str) -> None:
        self._sentry(name).unlink(missing_ok=True)

    def chore_paused(self, name: str) -> str | None:
        text = read_nofollow(self._sentry(name))
        if text is None:
            return None
        return text.strip() or "(no reason recorded)"

    # --- tick liveness and exclusion ---

    def mark_tick(self, mark: TickMark) -> None:
        payload = {"at": mark.at.isoformat(), "ledger_rows": mark.ledger_rows}
        tmp = self.root / "last_tick.tmp"
        write_nofollow(tmp, json.dumps(payload))
        os.replace(tmp, self.root / "last_tick")

    def last_tick(self) -> TickMark | None:
        text = read_nofollow(self.root / "last_tick")
        if text is None:
            return None
        data = json.loads(text)
        return TickMark(
            at=datetime.fromisoformat(str(data["at"])),
            ledger_rows=int(data["ledger_rows"]),
        )

    def tick_lock(self) -> AbstractContextManager[bool]:
        return self._flock(self.root / "tick.lock")

    def chore_lock(self, name: str) -> AbstractContextManager[None]:
        chore_dir = self.runs / check_chore_name(name)
        self._ensure_private(self.runs)
        self._ensure_private(chore_dir)
        return self._blocking_flock(chore_dir / "admission.lock")

    @staticmethod
    def _open_lock(path: Path) -> int:
        if path.is_symlink():
            raise UnsafeStatePath(f"{path} is a symlink; refusing to lock")
        return os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)

    @contextmanager
    def _blocking_flock(self, path: Path) -> Iterator[None]:
        fd = self._open_lock(path)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    @contextmanager
    def _flock(self, path: Path) -> Iterator[bool]:
        fh = os.fdopen(self._open_lock(path), "a+")
        try:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                yield False
                return
            try:
                yield True
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


class FsWorkspaces:
    """WorkspacesPort under the data directory (``.../chores/workspaces``)."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def ensure(self, chore: str) -> str:
        """The default cwd is trusted without a bindings check, so it must
        really be a directory under the data root: a pre-planted symlink at
        ``workspaces/<chore>`` (or at ``workspaces`` itself) pointing into
        the state or definitions root is refused, never followed."""
        check_chore_name(chore)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.root / chore
        if path.is_symlink() or self.root.is_symlink():
            raise UnsafeWorkspace(f"{path} is a symlink; refusing to use it as cwd")
        path.mkdir(exist_ok=True, mode=0o700)
        real_root = os.path.realpath(self.root)
        real = os.path.realpath(path)
        if not (real == real_root or real.startswith(real_root.rstrip("/") + "/")):
            raise UnsafeWorkspace(f"{path} resolves outside {self.root}")
        return real
