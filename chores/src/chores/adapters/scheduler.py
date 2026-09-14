"""Scheduler installers (CHORES.DESIGN.md Subsystem 2): a launchd
StartInterval agent on macOS, a systemd user timer on Linux, each running
``chores tick`` every tick interval. Install-time only -- there is no
runtime port (Rejections: "A SchedulerPort seam"). The launchd agent goes
through the login shell so ``.zshenv``/``.zprofile`` apply and the bare
``chores`` resolves through the tiered PATH (the skills-drift-monitor
plist mould)."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

LAUNCHD_LABEL = "com.tds.chores.tick"
SYSTEMD_UNIT = "chores-tick"

_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>-lc</string>
    <string>exec chores tick</string>
  </array>
  <key>StartInterval</key>
  <integer>{interval}</integer>
  <key>RunAtLoad</key>
  <true/>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
  </dict>
  <key>StandardOutPath</key>
  <string>/tmp/chores-tick.out.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/chores-tick.err.log</string>
  <key>ProcessType</key>
  <string>Background</string>
</dict>
</plist>
"""

_SERVICE = """[Unit]
Description=chores scheduler tick

[Service]
Type=oneshot
ExecStart=/bin/bash -lc 'exec chores tick'
"""

_TIMER = """[Unit]
Description=chores scheduler tick every {interval}s

[Timer]
OnBootSec=60s
OnUnitActiveSec={interval}s
AccuracySec=5s

[Install]
WantedBy=timers.target
"""

RunFn = Callable[[list[str]], int]


def _run_subprocess(argv: list[str]) -> int:
    return subprocess.run(argv, capture_output=True, check=False).returncode


class SchedulerInstaller(Protocol):
    def install(self, *, interval_sec: int, dry_run: bool = False) -> list[str]: ...

    def uninstall(self) -> list[str]: ...

    def installed(self) -> bool: ...

    def installed_interval(self) -> int | None: ...


class LaunchdInstaller:
    def __init__(self, *, home: Path, uid: int, run: RunFn = _run_subprocess) -> None:
        self.plist = home / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
        self._domain = f"gui/{uid}"
        self._run = run

    def install(self, *, interval_sec: int, dry_run: bool = False) -> list[str]:
        text = _PLIST.format(label=LAUNCHD_LABEL, interval=interval_sec)
        if dry_run:
            return [
                f"would write {self.plist}",
                f"would launchctl bootstrap {self._domain}",
            ]
        self.plist.parent.mkdir(parents=True, exist_ok=True)
        self.plist.write_text(text)
        self._run(["launchctl", "bootout", f"{self._domain}/{LAUNCHD_LABEL}"])
        rc = self._run(["launchctl", "bootstrap", self._domain, str(self.plist)])
        if rc != 0:
            return [f"wrote {self.plist}", f"launchctl bootstrap failed (exit {rc})"]
        return [
            f"wrote {self.plist}",
            f"bootstrapped {LAUNCHD_LABEL} every {interval_sec}s",
        ]

    def uninstall(self) -> list[str]:
        self._run(["launchctl", "bootout", f"{self._domain}/{LAUNCHD_LABEL}"])
        self.plist.unlink(missing_ok=True)
        return [f"booted out {LAUNCHD_LABEL}", f"removed {self.plist}"]

    def installed(self) -> bool:
        return self.plist.exists()

    def installed_interval(self) -> int | None:
        if not self.plist.exists():
            return None
        found = re.search(r"<integer>(\d+)</integer>", self.plist.read_text())
        return int(found.group(1)) if found else None


class SystemdInstaller:
    def __init__(self, *, home: Path, run: RunFn = _run_subprocess) -> None:
        self.unit_dir = home / ".config" / "systemd" / "user"
        self._run = run

    @property
    def timer(self) -> Path:
        return self.unit_dir / f"{SYSTEMD_UNIT}.timer"

    def install(self, *, interval_sec: int, dry_run: bool = False) -> list[str]:
        if dry_run:
            return [
                f"would write {self.timer} and its service",
                "would enable the timer",
            ]
        self.unit_dir.mkdir(parents=True, exist_ok=True)
        (self.unit_dir / f"{SYSTEMD_UNIT}.service").write_text(_SERVICE)
        self.timer.write_text(_TIMER.format(interval=interval_sec))
        self._run(["systemctl", "--user", "daemon-reload"])
        rc = self._run(
            ["systemctl", "--user", "enable", "--now", f"{SYSTEMD_UNIT}.timer"]
        )
        if rc != 0:
            return [f"wrote {self.timer}", f"systemctl enable failed (exit {rc})"]
        return [
            f"wrote {self.timer}",
            f"enabled {SYSTEMD_UNIT}.timer every {interval_sec}s",
        ]

    def uninstall(self) -> list[str]:
        self._run(["systemctl", "--user", "disable", "--now", f"{SYSTEMD_UNIT}.timer"])
        for name in (f"{SYSTEMD_UNIT}.timer", f"{SYSTEMD_UNIT}.service"):
            (self.unit_dir / name).unlink(missing_ok=True)
        self._run(["systemctl", "--user", "daemon-reload"])
        return [f"disabled and removed {SYSTEMD_UNIT}.timer"]

    def installed(self) -> bool:
        return self.timer.exists()

    def installed_interval(self) -> int | None:
        if not self.timer.exists():
            return None
        found = re.search(r"OnUnitActiveSec=(\d+)s", self.timer.read_text())
        return int(found.group(1)) if found else None


def installer_for(
    system: str, *, home: Path, uid: int, run: RunFn = _run_subprocess
) -> SchedulerInstaller | None:
    if system == "Darwin":
        return LaunchdInstaller(home=home, uid=uid, run=run)
    if system == "Linux":
        return SystemdInstaller(home=home, run=run)
    return None
