"""SubprocessRunner -- ProcessPort over subprocess (CHORES.DESIGN.md
Subsystem 3, "Process bound"): every child starts in its own session, the
whole group is SIGTERMed at the timeout and SIGKILLed after the grace,
process identity is pid plus start time so a reused pid never passes for a
live run, and CPU time comes from the child's rusage."""

from __future__ import annotations

import os
import resource
import signal
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass

from chores.ports.agent import ProcessIdentity
from chores.ports.errors import ProcessError
from chores.ports.process import ProcessRequest, ProcessResult

_START_TOLERANCE_SEC = 2.0


def process_start_time(pid: int) -> float | None:
    """Epoch seconds the process started, via ``ps`` (works on macOS and Linux)."""
    try:
        out = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = out.stdout.strip()
    if not text:
        return None
    try:
        return time.mktime(time.strptime(text, "%a %b %d %H:%M:%S %Y"))
    except ValueError:
        return None


@dataclass
class _Running:
    popen: subprocess.Popen[str]
    request: ProcessRequest
    identity: ProcessIdentity
    started_monotonic: float
    rusage_before: float

    def wait(self) -> ProcessResult:
        timed_out = False
        try:
            stdout, stderr = self.popen.communicate(
                input=self.request.stdin_text, timeout=self.request.timeout_sec
            )
        except subprocess.TimeoutExpired:
            timed_out = True
            self.terminate_group()
            try:
                stdout, stderr = self.popen.communicate(
                    timeout=self.request.kill_grace_sec
                )
            except subprocess.TimeoutExpired:
                _signal_group(self.identity.pgid, signal.SIGKILL)
                stdout, stderr = self.popen.communicate()
        cpu = _children_cpu() - self.rusage_before
        return ProcessResult(
            exit_code=self.popen.returncode
            if self.popen.returncode is not None
            else -1,
            stdout=stdout or "",
            stderr=stderr or "",
            timed_out=timed_out,
            cpu_seconds=max(cpu, 0.0),
            seconds=time.monotonic() - self.started_monotonic,
        )

    def terminate_group(self) -> None:
        _signal_group(self.identity.pgid, signal.SIGTERM)


def _signal_group(pgid: int, sig: signal.Signals) -> bool:
    try:
        os.killpg(pgid, sig)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return False


def _children_cpu() -> float:
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime + usage.ru_stime


class SubprocessRunner:
    def spawn(self, request: ProcessRequest) -> _Running:
        argv: Sequence[str] = request.argv
        try:
            popen = subprocess.Popen(
                list(argv),
                cwd=request.cwd,
                env=dict(request.env),
                stdin=subprocess.PIPE
                if request.stdin_text is not None
                else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
        except (OSError, ValueError) as e:
            raise ProcessError(f"could not start {argv[0]!r}: {e}") from e
        start = process_start_time(popen.pid)
        identity = ProcessIdentity(
            pid=popen.pid,
            pgid=popen.pid,  # start_new_session: the child leads its own group
            process_start=start if start is not None else time.time(),
        )
        return _Running(popen, request, identity, time.monotonic(), _children_cpu())

    def alive(self, pid: int, *, process_start: float) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        start = process_start_time(pid)
        if start is None or process_start == 0.0:
            return True
        return abs(start - process_start) <= _START_TOLERANCE_SEC

    def signal_group(self, pgid: int) -> bool:
        return _signal_group(pgid, signal.SIGTERM)

    def own_identity(self) -> ProcessIdentity:
        pid = os.getpid()
        start = process_start_time(pid)
        return ProcessIdentity(
            pid=pid,
            pgid=os.getpgid(pid),
            process_start=start if start is not None else 0.0,
        )
