"""adapters/lizard.py -- ComplexityPort over lizard.

lizard (PyPI, MIT; lmde/TECH_RADAR.md Trial) is run as a subprocess in a
scratch directory outside the repository, through `analyzer_process`:
the interpreter in isolated mode (`-I`, so neither the working directory
nor PYTHON* variables reach its import path), the file list on the
command line, `.gitignore` reading off, CSV out. The measured source is
untrusted, so the scratch copy carries none of lizard's in-source
directives: a function cannot exempt itself. The clock is the edge's own.
Absent or failing, it answers MetricsUnavailable naming the tool.
"""

from __future__ import annotations

import csv
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from adherence.adapters.analyzer_process import (
    NotRan,
    remaining,
    run_analyzer,
    write_sources,
)
from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.model import Complexity, Metrics, MetricsUnavailable

# --- Constants ---------------------------------------------------------------

LIZARD = (sys.executable, "-I", "-m", "lizard")
OPERATION = "measure complexity with lizard"
# lizard's CSV columns: NLOC, CCN, token, PARAM, length, location, file,
# function, long_name, start, end.
CCN, FILE, FUNCTION, START = 1, 6, 7, 9
COLUMNS = 11
# lizard's in-source directives, each rewritten in the scratch copy to text
# lizard does not act on: `#lizard forgive` (and `forgives`, `forgive
# global`) drops a function, and a comment holding `GENERATED CODE` ends the
# file. The rewrite keeps every line where it was.
DIRECTIVES = (
    (b"lizard forgive", b"lizard-forgive"),
    (b"GENERATED CODE", b"GENERATED-CODE"),
)

# --- Pure helpers ------------------------------------------------------------


def neutralised(data: bytes) -> bytes:
    """The source with every lizard directive rewritten so lizard ignores it."""
    for directive, inert in DIRECTIVES:
        data = data.replace(directive, inert)
    return data


def parse_csv(text: str, written: Mapping[str, str]) -> tuple[Complexity, ...]:
    """Each function row of lizard's CSV, keyed back to its repository path;
    the header and any row naming no written file are skipped."""
    found: list[Complexity] = []
    for row in csv.reader(text.splitlines()):
        if len(row) < COLUMNS or not row[CCN].isdigit() or not row[START].isdigit():
            continue
        path = written.get(row[FILE])
        if path is None:
            continue
        found.append(Complexity(path, row[FUNCTION], int(row[START]), int(row[CCN])))
    return tuple(found)


# --- Adapter -----------------------------------------------------------------


class LizardComplexity:
    """ComplexityPort over the lizard CLI."""

    def __init__(
        self,
        *,
        command: Sequence[str] = LIZARD,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._command = tuple(command)
        self._clock = clock

    def measure(
        self, sources: Mapping[str, bytes], deadline: Deadline | None
    ) -> Metrics | MetricsUnavailable | TimedOut:
        left = remaining(deadline, self._clock())
        if left is not None and left <= 0:
            return TimedOut(OPERATION)
        if not sources:
            return Metrics()
        with tempfile.TemporaryDirectory(prefix="adherence-lizard-") as scratch:
            root = Path(scratch)
            work = root / "work"
            work.mkdir()
            written = write_sources(
                root / "src", {p: neutralised(d) for p, d in sources.items()}
            )
            files = root / "files.txt"
            files.write_text("\n".join(written) + "\n", encoding="utf-8")
            command = (*self._command, "--csv", "--no-gitignore", "-f", str(files))
            ran = run_analyzer(
                command,
                cwd=work,
                scratch=root,
                timeout=remaining(deadline, self._clock()),
            )
            if isinstance(ran, NotRan):
                if ran.timed_out:
                    return TimedOut(OPERATION)
                return MetricsUnavailable(f"lizard {ran.reason}")
            if ran.returncode != 0:
                detail = ran.stderr.strip().splitlines()[-1:] or ["no message"]
                return MetricsUnavailable(
                    f"lizard exited {ran.returncode}: {detail[0]}"
                )
            return Metrics(complexity=parse_csv(ran.stdout, written))
