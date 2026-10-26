"""adapters/analyzer_process.py -- running an analyzer over untrusted sources.

The code under measurement is data (ARCHITECTURE.ARCH-ADHERENCE.md,
Security mitigations): its bytes are written into a scratch directory
outside the repository, the analyzer is spawned there with its
configuration on the command line, an allowlisted environment (PATH,
LANG, and HOME and TMPDIR set to the scratch directory), and the time left
before the Deadline as its timeout. Nothing from the repository is
imported, built or run.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from adherence.domain.deadline import Deadline

# --- Constants ---------------------------------------------------------------

# An extension a generated name keeps: one an analyzer reads a language by.
PLAIN_SUFFIX = re.compile(r"\.[A-Za-z0-9_+-]{1,16}")

# --- Values ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Ran:
    """An analyzer's run: its exit status and what it printed."""

    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True, slots=True)
class NotRan:
    """Why an analyzer could not be run at all, or did not finish in time."""

    reason: str
    timed_out: bool = False


# --- Effectful helpers -------------------------------------------------------


def remaining(deadline: Deadline | None, now: float) -> float | None:
    """The seconds left before the deadline; None when unbounded."""
    return None if deadline is None else deadline.epoch_seconds - now


def write_sources(root: Path, sources: Mapping[str, bytes]) -> dict[str, str]:
    """Each source written under root at its repository path; the written
    file's absolute path mapped to the repository path. A path that would
    leave root is not written."""
    written: dict[str, str] = {}
    base = root.resolve()
    for path, data in sources.items():
        target = (base / path).resolve()
        if not target.is_relative_to(base) or target == base:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        written[str(target)] = path
    return written


def write_numbered(root: Path, sources: Mapping[str, bytes]) -> dict[str, str]:
    """Each source written flat under root by a generated name -- its index
    and its extension, when that is plain -- so no repository path (one
    holding a newline, say) reaches the analyzer; the written file's
    absolute path mapped to the repository path."""
    base = root.resolve()
    base.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    for index, path in enumerate(sorted(sources)):
        suffix = PurePosixPath(path).suffix
        plain = suffix if PLAIN_SUFFIX.fullmatch(suffix) else ""
        target = base / f"{index:06d}{plain}"
        target.write_bytes(sources[path])
        written[str(target)] = path
    return written


def allowlisted_environment(scratch: Path) -> dict[str, str]:
    """The only environment an analyzer receives."""
    return {
        "PATH": os.environ.get("PATH", os.defpath),
        "LANG": "C.UTF-8",
        "HOME": str(scratch),
        "TMPDIR": str(scratch),
    }


def run_analyzer(
    command: Sequence[str], *, cwd: Path, scratch: Path, timeout: float | None
) -> Ran | NotRan:
    """Run the analyzer once, in cwd, with the allowlisted environment."""
    if timeout is not None and timeout <= 0:
        return NotRan("no time left before the deadline", timed_out=True)
    try:
        done = subprocess.run(
            list(command),
            cwd=cwd,
            env=allowlisted_environment(scratch),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return NotRan("did not finish before the deadline", timed_out=True)
    except OSError as error:
        return NotRan(f"cannot be run: {error}")
    return Ran(done.returncode, done.stdout, done.stderr)
