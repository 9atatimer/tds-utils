"""FsRunStore -- the state directory as a RunStorePort (CHORES.DESIGN.md Data
Model: ``runs/<chore>/<run-id>/``, ``ledger.ndjson``, ``notifications.ndjson``,
``last_tick``, ``PAUSED``, ``paused/<chore>``, ``tick.lock``; mode 0700).

Records are JSON documents rewritten on every transition; artifacts and the
two NDJSON files are append-only; the tick lock is an OS-held ``flock`` that
dies with the process.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import shutil
from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime
from pathlib import Path

from chores.domain.budget import Usage
from chores.domain.errors import InfrastructureError
from chores.domain.kinds import Kind
from chores.domain.run import Billing, RunRecord, RunStatus
from chores.ports.store import Artifact, Notification, TickMark

_RUN_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class InvalidRunId(InfrastructureError):
    """A run id that is not a single path-safe segment (CLI input reaches here)."""


def check_run_id(run_id: str) -> str:
    if not _RUN_ID_RE.match(run_id):
        raise InvalidRunId(f"not a run id: {run_id!r}")
    return run_id


_ARTIFACTS: tuple[Artifact, ...] = (
    "definition.md",
    "transcript.jsonl",
    "stdout.log",
    "stderr.log",
    "errors.log",
)


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
        self._ensure_private(root / "paused")

    # --- helpers ---

    @staticmethod
    def _ensure_private(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path, 0o700)

    def _run_dir(self, run_id: str) -> Path:
        check_run_id(run_id)
        chore = run_id.rsplit("-", 2)[0]
        return self.runs / chore / run_id

    def _find_run_dir(self, run_id: str) -> Path | None:
        if not _RUN_ID_RE.match(run_id):
            return None
        direct = self._run_dir(run_id)
        if direct.is_dir():
            return direct
        for candidate in self.runs.glob(f"*/{run_id}"):
            if candidate.is_dir():
                return candidate
        return None

    @staticmethod
    def _append(path: Path, text: str) -> None:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(text)

    @staticmethod
    def _read_ndjson(path: Path) -> list[dict[str, object]]:
        if not path.exists():
            return []
        rows: list[dict[str, object]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    # --- records ---

    def write_record(self, record: RunRecord) -> None:
        run_dir = self._run_dir(record.run_id)
        self._ensure_private(run_dir.parent)
        self._ensure_private(run_dir)
        tmp = run_dir / "run.json.tmp"
        tmp.write_text(json.dumps(record_to_json(record), indent=1), encoding="utf-8")
        os.replace(tmp, run_dir / "run.json")

    def read_record(self, run_id: str) -> RunRecord | None:
        run_dir = self._find_run_dir(run_id)
        if run_dir is None or not (run_dir / "run.json").exists():
            return None
        return record_from_json(
            json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        )

    def records(
        self, *, chore: str | None = None, since: datetime | None = None
    ) -> Sequence[RunRecord]:
        out: list[RunRecord] = []
        chore_dirs = [self.runs / chore] if chore else sorted(self.runs.iterdir())
        for chore_dir in chore_dirs:
            if not chore_dir.is_dir():
                continue
            for run_json in chore_dir.glob("*/run.json"):
                record = record_from_json(
                    json.loads(run_json.read_text(encoding="utf-8"))
                )
                if since is None or record.started >= since:
                    out.append(record)
        return sorted(out, key=lambda r: (r.started, r.run_id), reverse=True)

    # --- artifacts ---

    def append_artifact(self, run_id: str, name: Artifact, text: str) -> int:
        run_dir = self._run_dir(run_id)
        self._ensure_private(run_dir)
        self._append(run_dir / name, text)
        return self.run_dir_bytes(run_id)

    def read_artifact(self, run_id: str, name: Artifact) -> str:
        run_dir = self._find_run_dir(run_id)
        if run_dir is None or not (run_dir / name).exists():
            return ""
        return (run_dir / name).read_text(encoding="utf-8")

    def run_dir_bytes(self, run_id: str) -> int:
        run_dir = self._find_run_dir(run_id)
        if run_dir is None:
            return 0
        return sum(p.stat().st_size for p in run_dir.iterdir() if p.is_file())

    def artifacts(self, run_id: str) -> Iterator[Artifact]:
        run_dir = self._find_run_dir(run_id)
        if run_dir is None:
            return iter(())
        return (name for name in _ARTIFACTS if (run_dir / name).exists())

    def delete_run(self, run_id: str) -> bool:
        run_dir = self._find_run_dir(run_id)
        if run_dir is None:
            return False
        shutil.rmtree(run_dir, ignore_errors=True)
        return True

    # --- kill requests ---

    def request_kill(self, run_id: str) -> None:
        run_dir = self._run_dir(run_id)
        self._ensure_private(run_dir)
        (run_dir / "KILL").write_text("", encoding="utf-8")

    def kill_requested(self, run_id: str) -> bool:
        run_dir = self._find_run_dir(run_id)
        return run_dir is not None and (run_dir / "KILL").exists()

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
        (self.root / "PAUSED").write_text(reason, encoding="utf-8")

    def unpause(self) -> None:
        (self.root / "PAUSED").unlink(missing_ok=True)

    def paused(self) -> str | None:
        path = self.root / "PAUSED"
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8").strip() or "(no reason recorded)"

    def pause_chore(self, name: str, reason: str) -> None:
        (self.root / "paused" / name).write_text(reason, encoding="utf-8")

    def resume_chore(self, name: str) -> None:
        (self.root / "paused" / name).unlink(missing_ok=True)

    def chore_paused(self, name: str) -> str | None:
        path = self.root / "paused" / name
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8").strip() or "(no reason recorded)"

    # --- tick liveness and exclusion ---

    def mark_tick(self, mark: TickMark) -> None:
        payload = {"at": mark.at.isoformat(), "ledger_rows": mark.ledger_rows}
        tmp = self.root / "last_tick.tmp"
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, self.root / "last_tick")

    def last_tick(self) -> TickMark | None:
        path = self.root / "last_tick"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return TickMark(
            at=datetime.fromisoformat(str(data["at"])),
            ledger_rows=int(data["ledger_rows"]),
        )

    def tick_lock(self) -> AbstractContextManager[bool]:
        return self._flock(self.root / "tick.lock")

    @contextmanager
    def _flock(self, path: Path) -> Iterator[bool]:
        fh = path.open("a+")
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
        path = self.root / chore
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        return str(path)
