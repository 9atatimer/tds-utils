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
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import IO

from chores.ports.agent import ProcessIdentity
from chores.ports.errors import ProcessError
from chores.ports.process import ProcessRequest, ProcessResult

_START_TOLERANCE_SEC = 2.0
UNKNOWN_START = 0.0
"""A recorded ``process_start`` of 0.0 means the start time could not be
read when the process was spawned. Identity is then unknown, and unknown
fails closed: ``alive`` says False, so the tick closes the run and
``chores kill`` never signals a group it cannot vouch for."""


def process_start_time(pid: int) -> float | None:
    """Epoch seconds the process started, via ``ps`` (macOS and Linux), read
    under ``LC_ALL=C`` so ``lstart`` is the English form ``strptime`` expects
    whatever the host locale is. None when ps failed or printed nothing."""
    env = {**os.environ, "LC_ALL": "C", "LANG": "C", "LC_TIME": "C"}
    try:
        out = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            env=env,
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


def _start_or_unknown(pid: int) -> float:
    start = process_start_time(pid)
    if start is None:
        start = process_start_time(pid)  # one retry: ps hiccups are transient
    return start if start is not None else UNKNOWN_START


_CHUNK = 64 * 1024


@dataclass
class _Capture:
    """One stream's bounded capture: the first ``cap`` bytes are kept, the
    rest are counted as lost. Memory never exceeds the cap however much the
    child writes."""

    cap: int | None
    data: bytearray = field(default_factory=bytearray)
    truncated: bool = False

    def feed(self, chunk: bytes) -> None:
        if self.cap is None:
            self.data += chunk
            return
        room = self.cap - len(self.data)
        if len(chunk) > room:
            self.truncated = True
        if room > 0:
            self.data += chunk[:room]

    def text(self) -> str:
        return self.data.decode("utf-8", errors="replace")


def _drain(stream: IO[bytes], capture: _Capture) -> None:
    """Reader-thread body: pull the pipe to EOF so the child never blocks on
    a full buffer, keeping only what the cap allows."""
    fd = stream.fileno()
    try:
        while chunk := os.read(fd, _CHUNK):
            capture.feed(chunk)
    except OSError:
        pass
    finally:
        stream.close()


def _feed_stdin(stream: IO[bytes], text: str) -> None:
    try:
        stream.write(text.encode("utf-8"))
        stream.close()
    except OSError:  # BrokenPipe: the child stopped reading, its business
        pass


def _thread(target: Callable[..., None], *args: object) -> threading.Thread:
    t = threading.Thread(target=target, args=args, daemon=True)
    t.start()
    return t


@dataclass
class _Running:
    popen: subprocess.Popen[bytes]
    request: ProcessRequest
    identity: ProcessIdentity
    started_monotonic: float
    rusage_before: float

    def wait(self) -> ProcessResult:
        """Block until exit or timeout. Output is streamed into bounded
        captures by reader threads rather than buffered whole by
        ``communicate``: a command that prints without end costs the runner
        at most ``max_output_bytes`` per stream, not its memory."""
        cap = self.request.max_output_bytes
        out, err = _Capture(cap), _Capture(cap)
        assert self.popen.stdout is not None and self.popen.stderr is not None
        threads = [
            _thread(_drain, self.popen.stdout, out),
            _thread(_drain, self.popen.stderr, err),
        ]
        if self.popen.stdin is not None:
            threads.append(
                _thread(_feed_stdin, self.popen.stdin, self.request.stdin_text or "")
            )
        timed_out = False
        try:
            self.popen.wait(timeout=self.request.timeout_sec)
        except subprocess.TimeoutExpired:
            timed_out = True
            self.terminate_group()
            try:
                self.popen.wait(timeout=self.request.kill_grace_sec)
            except subprocess.TimeoutExpired:
                _signal_group(self.identity.pgid, signal.SIGKILL)
                self.popen.wait()
        for t in threads:
            # EOF follows the group's exit; a grandchild that escaped the
            # group and still holds the pipe is not waited for without end
            t.join(timeout=self.request.kill_grace_sec)
        cpu = _children_cpu() - self.rusage_before
        return ProcessResult(
            exit_code=self.popen.returncode
            if self.popen.returncode is not None
            else -1,
            stdout=out.text(),
            stderr=err.text(),
            timed_out=timed_out,
            cpu_seconds=max(cpu, 0.0),
            seconds=time.monotonic() - self.started_monotonic,
            output_truncated=out.truncated or err.truncated,
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
                start_new_session=True,
            )
        except (OSError, ValueError) as e:
            raise ProcessError(f"could not start {argv[0]!r}: {e}") from e
        identity = ProcessIdentity(
            pid=popen.pid,
            pgid=popen.pid,  # start_new_session: the child leads its own group
            process_start=_start_or_unknown(popen.pid),  # never a guess
        )
        return _Running(popen, request, identity, time.monotonic(), _children_cpu())

    def alive(self, pid: int, *, process_start: float) -> bool:
        """Is that exact process running? Fails closed: an unknown recorded
        identity, a pid we may not inspect, or a start time ps cannot give
        now all answer False rather than vouching for a pid that may have
        been recycled."""
        if process_start == UNKNOWN_START:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return False
        start = process_start_time(pid)
        if start is None:
            return False
        return abs(start - process_start) <= _START_TOLERANCE_SEC

    def signal_group(self, pgid: int) -> bool:
        return _signal_group(pgid, signal.SIGTERM)

    def own_identity(self) -> ProcessIdentity:
        pid = os.getpid()
        return ProcessIdentity(
            pid=pid, pgid=os.getpgid(pid), process_start=_start_or_unknown(pid)
        )
