"""Host adapters: system clock, battery state, reachability probe, desktop
notification. Each is the smallest mechanism that satisfies its port; the
Linux and macOS differences stay inside this file."""

from __future__ import annotations

import platform
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from chores.adapters.http import probe


class SystemClock:
    def now_local(self) -> datetime:
        return datetime.now().replace(microsecond=0)

    def now_utc(self) -> datetime:
        return datetime.now(UTC).replace(tzinfo=None, microsecond=0)

    def local_from_utc(self, at: datetime) -> datetime:
        return at.replace(tzinfo=UTC).astimezone().replace(tzinfo=None)


class SystemPower:
    """``pmset -g batt`` on macOS, ``/sys/class/power_supply`` on Linux, else AC."""

    def on_battery(self) -> bool:
        if platform.system() == "Darwin":
            try:
                out = subprocess.run(
                    ["pmset", "-g", "batt"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                return False
            return "Battery Power" in out.stdout
        return linux_on_battery(Path("/sys/class/power_supply"))


def _read(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def linux_on_battery(supplies: Path) -> bool:
    """Discharging? Any ``type == Mains`` supply that reports ``online``
    decides (AC, ADP1, ACAD, USB-C PD all present that way); with no mains
    supply, a battery whose ``status`` is Discharging decides; otherwise
    assume mains (a desktop has no battery and must never defer)."""
    if not supplies.is_dir():
        return False
    for supply in sorted(supplies.iterdir()):
        if _read(supply / "type") == "Mains":
            online = _read(supply / "online")
            if online is not None:
                return online == "0"
    for supply in sorted(supplies.iterdir()):
        if _read(supply / "type") == "Battery":
            if _read(supply / "status") == "Discharging":
                return True
    return False


class SocketNetwork:
    def reachable(self, url: str, *, timeout_sec: float) -> bool:
        return probe(url, timeout_sec=timeout_sec)


class DesktopNotifier:
    """osascript on macOS with the text passed as an argument (never
    interpolated), notify-send on Linux when present, otherwise a no-op."""

    def alert(self, *, title: str, text: str) -> None:
        if platform.system() == "Darwin":
            script = [
                "osascript",
                "-e",
                "on run argv",
                "-e",
                "display notification (item 2 of argv) with title (item 1 of argv)",
                "-e",
                "end run",
                title,
                text,
            ]
            self._run(script)
        elif shutil.which("notify-send"):
            self._run(["notify-send", title, text])

    @staticmethod
    def _run(argv: list[str]) -> None:
        try:
            subprocess.run(argv, capture_output=True, timeout=10, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return
