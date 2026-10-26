"""adapters/inline_worker.py -- WorkerPort that runs the job in process.

The fake behind WorkerPort (ARCHITECTURE.ARCH-ADHERENCE.md, Module map):
it reads no clock and ends nothing on time; scripted with `ends_after`, it
ends the job once that many checks have finished, by unwinding it from the
sink, so the job asks no port anything after. Tests bind it; the hook
binds process_worker.
"""

from __future__ import annotations

from adherence.domain.deadline import Deadline
from adherence.domain.report import FinishedCheck, Report
from adherence.ports.worker import Ended, Job


class _EndedByScript(BaseException):
    """Unwinds a job the script ends. A BaseException, so no check
    boundary's `except Exception` can swallow it."""


class _ScriptedSink:
    """Keeps every finished check and ends the job at the scripted count."""

    def __init__(self, ends_after: int | None) -> None:
        self._ends_after = ends_after
        self.finished: list[FinishedCheck] = []

    def __call__(self, check: FinishedCheck) -> None:
        self.finished.append(check)
        if self._ends_after is not None and len(self.finished) >= self._ends_after:
            raise _EndedByScript


class InlineWorker:
    """WorkerPort that runs the job here, to the end unless scripted."""

    def __init__(self, *, ends_after: int | None = None) -> None:
        self._ends_after = ends_after

    def run(self, job: Job, deadline: Deadline) -> Report | Ended:
        sink = _ScriptedSink(self._ends_after)
        try:
            return job(sink)
        except _EndedByScript:
            return Ended(
                tuple(sink.finished),
                f"ended by the script after {len(sink.finished)} checks",
            )
