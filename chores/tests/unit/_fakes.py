"""In-memory fakes for every port (testing-python skill: fakes over mocks).
Imported explicitly by tests; nothing here is a fixture."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from chores.domain.run import Billing, RunRecord
from chores.ports.agent import AgentResult, AgentTask, ProcessIdentity
from chores.ports.completion import CompletionRequest, CompletionResponse
from chores.ports.errors import BackendError, SecretUnavailable
from chores.ports.process import ProcessRequest, ProcessResult
from chores.ports.store import Artifact, Notification, TickMark


class FakeClock:
    def __init__(
        self, local: datetime, *, utc_offset: timedelta = timedelta(0)
    ) -> None:
        self._local = local
        self._offset = utc_offset

    def now_local(self) -> datetime:
        return self._local

    def now_utc(self) -> datetime:
        return self._local - self._offset

    def advance(self, seconds: float) -> None:
        self._local = self._local + timedelta(seconds=seconds)


class FakePower:
    def __init__(self, *, on_battery: bool = False) -> None:
        self.battery = on_battery

    def on_battery(self) -> bool:
        return self.battery


class FakeNetwork:
    def __init__(self, *, online: bool = True) -> None:
        self.online = online
        self.probed: list[str] = []

    def reachable(self, url: str, *, timeout_sec: float) -> bool:
        self.probed.append(url)
        return self.online


class FakeSecrets:
    def __init__(self, values: Mapping[str, str] | None = None) -> None:
        self.values = dict(values or {})
        self.resolved: list[str] = []

    def resolve(self, reference: str, *, timeout_sec: int) -> str:
        self.resolved.append(reference)
        if reference not in self.values:
            raise SecretUnavailable(f"no such secret: {reference}")
        return self.values[reference]


class FakeNotifier:
    def __init__(self) -> None:
        self.alerts: list[tuple[str, str]] = []

    def alert(self, *, title: str, text: str) -> None:
        self.alerts.append((title, text))


class FakeCompletion:
    def __init__(
        self,
        *,
        text: str = "ok",
        tokens_in: int = 10,
        tokens_out: int = 5,
        usd: float | None = 0.001,
        billing: Billing = Billing.METERED,
        error: BackendError | None = None,
    ) -> None:
        self.text, self.tokens_in, self.tokens_out = text, tokens_in, tokens_out
        self.usd, self.billing, self.error = usd, billing, error
        self.requests: list[CompletionRequest] = []

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return CompletionResponse(
            text=self.text,
            tokens_in=self.tokens_in,
            tokens_out=self.tokens_out,
            usd=self.usd,
            provider="fake",
            model=request.model,
            latency_sec=0.01,
            billing=self.billing,
        )


class FakeAgent:
    def __init__(
        self,
        *,
        text: str = "done",
        tokens_in: int = 100,
        tokens_out: int = 50,
        usd: float | None = 0.05,
        turns: int = 3,
        exit_code: int = 0,
        timed_out: bool = False,
        error: BackendError | None = None,
    ) -> None:
        self.result = AgentResult(
            text=text,
            events=[{"type": "text", "text": text}],
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            usd=usd,
            turns=turns,
            billing=Billing.SUBSCRIPTION,
            exit_code=exit_code,
            timed_out=timed_out,
            cpu_seconds=0.5,
        )
        self.error = error
        self.tasks: list[AgentTask] = []

    def run(
        self, task: AgentTask, *, on_start: Callable[[ProcessIdentity], None]
    ) -> AgentResult:
        self.tasks.append(task)
        on_start(ProcessIdentity(pid=4242, pgid=4242, process_start=1.0))
        if self.error is not None:
            raise self.error
        return self.result


@dataclass
class FakeRunning:
    result: ProcessResult
    identity: ProcessIdentity = field(
        default_factory=lambda: ProcessIdentity(pid=777, pgid=777, process_start=2.0)
    )
    terminated: bool = False

    def wait(self) -> ProcessResult:
        return self.result

    def terminate_group(self) -> None:
        self.terminated = True


class FakeProcess:
    def __init__(
        self,
        *,
        exit_code: int = 0,
        stdout: str = "",
        stderr: str = "",
        timed_out: bool = False,
        alive_pids: set[int] | None = None,
    ) -> None:
        self.result = ProcessResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            cpu_seconds=0.2,
            seconds=1.5,
        )
        self.requests: list[ProcessRequest] = []
        self.alive_pids = alive_pids if alive_pids is not None else set()
        self.signalled: list[int] = []

    def spawn(self, request: ProcessRequest) -> FakeRunning:
        self.requests.append(request)
        return FakeRunning(self.result)

    def alive(self, pid: int, *, process_start: float) -> bool:
        return pid in self.alive_pids

    def signal_group(self, pgid: int) -> bool:
        self.signalled.append(pgid)
        return True

    def own_identity(self) -> ProcessIdentity:
        return ProcessIdentity(pid=100, pgid=100, process_start=0.25)


class FakeWorkspaces:
    def __init__(self, root: str = "/data/workspaces") -> None:
        self.root = root
        self.ensured: list[str] = []

    def ensure(self, chore: str) -> str:
        self.ensured.append(chore)
        return f"{self.root}/{chore}"


class FakeRunStore:
    """In-memory RunStorePort with the same semantics the contract tests pin."""

    def __init__(self) -> None:
        self._records: dict[str, RunRecord] = {}
        self._artifacts: dict[tuple[str, str], str] = {}
        self._ledger: list[Mapping[str, object]] = []
        self._notifications: list[Notification] = []
        self._paused: str | None = None
        self._chore_paused: dict[str, str] = {}
        self._tick: TickMark | None = None
        self._kills: set[str] = set()
        self.lock_held = False

    def request_kill(self, run_id: str) -> None:
        self._kills.add(run_id)

    def kill_requested(self, run_id: str) -> bool:
        return run_id in self._kills

    def write_record(self, record: RunRecord) -> None:
        self._records[record.run_id] = record

    def read_record(self, run_id: str) -> RunRecord | None:
        return self._records.get(run_id)

    def records(
        self, *, chore: str | None = None, since: datetime | None = None
    ) -> Sequence[RunRecord]:
        out = [
            r
            for r in self._records.values()
            if (chore is None or r.chore == chore)
            and (since is None or r.started >= since)
        ]
        return sorted(out, key=lambda r: (r.started, r.run_id), reverse=True)

    def append_artifact(self, run_id: str, name: Artifact, text: str) -> int:
        key = (run_id, name)
        self._artifacts[key] = self._artifacts.get(key, "") + text
        return self.run_dir_bytes(run_id)

    def read_artifact(self, run_id: str, name: Artifact) -> str:
        return self._artifacts.get((run_id, name), "")

    def run_dir_bytes(self, run_id: str) -> int:
        return sum(
            len(v.encode()) for (rid, _), v in self._artifacts.items() if rid == run_id
        )

    def artifacts(self, run_id: str) -> Iterator[Artifact]:
        return (name for (rid, name) in self._artifacts if rid == run_id)

    def append_ledger(self, row: Mapping[str, object]) -> None:
        self._ledger.append(dict(row))

    def ledger_rows(
        self, *, since: datetime | None = None
    ) -> Sequence[Mapping[str, object]]:
        if since is None:
            return list(self._ledger)
        return [
            r
            for r in self._ledger
            if datetime.fromisoformat(str(r["started"])) >= since
        ]

    def ledger_count(self) -> int:
        return len(self._ledger)

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
            id=f"n{len(self._notifications) + 1}",
            ts=at,
            run_id=run_id,
            chore=chore,
            level=level,
            text=text,
            read=False,
        )
        self._notifications.append(n)
        return n

    def notifications(self, *, unread_only: bool = True) -> Sequence[Notification]:
        return [n for n in self._notifications if not (unread_only and n.read)]

    def dismiss(self, notification_id: str) -> bool:
        for i, n in enumerate(self._notifications):
            if n.id == notification_id:
                self._notifications[i] = Notification(
                    n.id, n.ts, n.run_id, n.chore, n.level, n.text, True
                )
                return True
        return False

    def pause(self, reason: str) -> None:
        self._paused = reason

    def unpause(self) -> None:
        self._paused = None

    def paused(self) -> str | None:
        return self._paused

    def pause_chore(self, name: str, reason: str) -> None:
        self._chore_paused[name] = reason

    def resume_chore(self, name: str) -> None:
        self._chore_paused.pop(name, None)

    def chore_paused(self, name: str) -> str | None:
        return self._chore_paused.get(name)

    def mark_tick(self, mark: TickMark) -> None:
        self._tick = mark

    def last_tick(self) -> TickMark | None:
        return self._tick

    def tick_lock(self) -> AbstractContextManager[bool]:
        return self._lock()

    @contextmanager
    def _lock(self) -> Iterator[bool]:
        if self.lock_held:
            yield False
            return
        self.lock_held = True
        try:
            yield True
        finally:
            self.lock_held = False
