"""structlog as JSON lines in the daemon's state directory.

One event per line, with ``timestamp`` (ISO 8601, UTC) and ``level``. The
file is created owner-only (it names the pages saved). Goal 2's interval is
read from it: each filed job logs ``job.applied`` with ``received_at``,
``applied_at`` and ``interval_ms`` (``adapters/dispatch.py``).
"""

import os
from pathlib import Path
from typing import Final, TextIO

import structlog

FILE_MODE: Final = 0o600

_open: list[TextIO] = []


def _close_previous() -> None:
    while _open:
        _open.pop().close()


def configure_logging(path: Path | None) -> None:
    """Log JSON lines to ``path`` (appending); ``None`` restores structlog's
    defaults (console), closing a file this module opened."""
    _close_previous()
    if path is None:
        structlog.reset_defaults()
        return
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, FILE_MODE)
    os.chmod(path, FILE_MODE)
    stream = os.fdopen(fd, "a", encoding="utf-8", buffering=1)
    _open.append(stream)
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.WriteLoggerFactory(file=stream),
        cache_logger_on_first_use=False,
    )
