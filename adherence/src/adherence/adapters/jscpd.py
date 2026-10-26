"""adapters/jscpd.py -- DuplicationPort over jscpd.

jscpd (npm, MIT; lmde/TECH_RADAR.md Trial; pinned in adherence/package-
lock.json, installed with `npm ci --ignore-scripts`) is run as a
subprocess in a scratch directory outside the repository, through
`analyzer_process`: an empty configuration file named on the command line
so none is discovered, `.gitignore` reading off, symbolic links not
followed, absolute paths and the JSON reporter into the scratch
directory. The sources are written under generated names into one
directory, which jscpd is pointed at with an explicit pattern, so neither
a repository's size nor any path reaches the command line. The measured
source is untrusted, so the scratch copy carries none of jscpd's
in-source markers: a clone cannot hide itself. The clock is the edge's
own. Absent or failing, it answers MetricsUnavailable naming the tool.
"""

from __future__ import annotations

import json
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from adherence.adapters.analyzer_process import (
    NotRan,
    remaining,
    run_analyzer,
    write_numbered,
)
from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.model import Clone, Metrics, MetricsUnavailable, Span

# --- Constants ---------------------------------------------------------------

OPERATION = "find clones with jscpd"
REPORT = "jscpd-report.json"
# The detection floor: the ceiling the Duplication check applies is a
# Limits value above it.
MIN_LINES = 5
MIN_TOKENS = 50
# Every file of the scratch directory the sources are written to.
EVERY_FILE = "**/*"
# jscpd's in-source markers (`jscpd:ignore-start` .. `jscpd:ignore-end`
# skips what they fence), rewritten in the scratch copy to text jscpd does
# not act on, keeping every line where it was.
MARKER, INERT = b"jscpd:ignore-", b"jscpd-ignore-"

# --- Pure helpers ------------------------------------------------------------


def neutralised(data: bytes) -> bytes:
    """The source with every jscpd marker rewritten so jscpd ignores it."""
    return data.replace(MARKER, INERT)


def _span(side: object, written: Mapping[str, str]) -> Span | None:
    if not isinstance(side, dict):
        return None
    path = written.get(str(side.get("name")))
    start, end = side.get("start"), side.get("end")
    if path is None or not isinstance(start, int) or not isinstance(end, int):
        return None
    return Span(path, start, end)


def parse_report(document: object, written: Mapping[str, str]) -> tuple[Clone, ...]:
    """Each duplicate of jscpd's JSON report keyed back to its repository
    paths, the earlier path first; a duplicate naming no written file is
    skipped."""
    duplicates = document.get("duplicates") if isinstance(document, dict) else None
    clones: list[Clone] = []
    for duplicate in duplicates if isinstance(duplicates, list) else []:
        if not isinstance(duplicate, dict):
            continue
        first = _span(duplicate.get("firstFile"), written)
        second = _span(duplicate.get("secondFile"), written)
        lines = duplicate.get("lines")
        if first is None or second is None or not isinstance(lines, int):
            continue
        if (second.path, second.start) < (first.path, first.start):
            first, second = second, first
        clones.append(Clone(first, second, lines))
    return tuple(sorted(clones, key=lambda c: (c.first.path, c.first.start)))


# --- Adapter -----------------------------------------------------------------


class JscpdDuplication:
    """DuplicationPort over the jscpd CLI at `command`."""

    def __init__(
        self,
        *,
        command: Sequence[str],
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._command = tuple(command)
        self._clock = clock

    def _command_line(self, root: Path, sources: Path) -> tuple[str, ...]:
        config = root / "jscpd.json"
        config.write_text("{}\n", encoding="utf-8")
        return (
            *self._command,
            "--config",
            str(config),
            "--no-gitignore",
            "--absolute",
            "--min-lines",
            str(MIN_LINES),
            "--min-tokens",
            str(MIN_TOKENS),
            "--reporters",
            "json",
            "--output",
            str(root / "out"),
            "--silent",
            "--no-tips",
            "--pattern",
            EVERY_FILE,
            str(sources),
        )

    def measure(
        self, sources: Mapping[str, bytes], deadline: Deadline | None
    ) -> Metrics | MetricsUnavailable | TimedOut:
        left = remaining(deadline, self._clock())
        if left is not None and left <= 0:
            return TimedOut(OPERATION)
        if not sources:
            return Metrics()
        with tempfile.TemporaryDirectory(prefix="adherence-jscpd-") as scratch:
            root = Path(scratch)
            work = root / "work"
            work.mkdir()
            written = write_numbered(
                root / "src", {p: neutralised(d) for p, d in sources.items()}
            )
            ran = run_analyzer(
                self._command_line(root, root / "src"),
                cwd=work,
                scratch=root,
                timeout=remaining(deadline, self._clock()),
            )
            if isinstance(ran, NotRan):
                if ran.timed_out:
                    return TimedOut(OPERATION)
                return MetricsUnavailable(f"jscpd {ran.reason}")
            if ran.returncode != 0:
                detail = ran.stderr.strip().splitlines()[-1:] or ["no message"]
                return MetricsUnavailable(f"jscpd exited {ran.returncode}: {detail[0]}")
            report = root / "out" / REPORT
            if not report.is_file():
                return Metrics()
            try:
                document = json.loads(report.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                return MetricsUnavailable(f"jscpd's report cannot be read: {error}")
            return Metrics(clones=parse_report(document, written))
