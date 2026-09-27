"""Suite-wide pytest setup: temp paths short enough for a unix socket.

A unix socket address holds 104 bytes on macOS (108 on Linux). pytest's
default temp root on macOS sits under ``$TMPDIR`` (``/var/folders/.../T/``),
so ``tmp_path / "state" / "dynomark" / "daemon.sock"`` runs past 104 bytes
and every socket test would fail to bind there, though green on Linux.
Unless ``--basetemp`` is given, the suite's temp root is a fresh directory
directly under ``/tmp``, removed when the run ends.
"""

import shutil
import tempfile
from pathlib import Path

import pytest

_made: list[Path] = []


def pytest_configure(config: pytest.Config) -> None:
    if config.option.basetemp:
        return
    base = Path(tempfile.mkdtemp(prefix="dm-", dir="/tmp"))
    _made.append(base)
    config.option.basetemp = str(base)


def pytest_unconfigure(config: pytest.Config) -> None:
    while _made:
        shutil.rmtree(_made.pop(), ignore_errors=True)
