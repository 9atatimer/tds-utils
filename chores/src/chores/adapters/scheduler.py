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
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol
from xml.sax.saxutils import escape

from chores.domain.errors import InfrastructureError

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
  <dict>{env}
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
Type=oneshot{env}
# A user service inherits no shell PATH; name the runtime tiers explicitly
# (dist install, release worktree, fresh-clone fallback, ~/.local/bin) so a
# bare `chores` resolves -- the same tier order as AGENT.md's PATH table.
Environment=PATH=%h/.tds/dist/current/bin:%h/.tds/release/bin:%h/workplace/tds-utils/bin:%h/.local/bin:/usr/local/bin:/usr/bin:/bin
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


def _remove_quietly(path: Path) -> None:
    """Best-effort cleanup of a unit we may have half-written: the failure
    being reported is the write, not whether the leftover could be removed."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _run_subprocess(argv: list[str]) -> int:
    try:
        return subprocess.run(argv, capture_output=True, check=False).returncode
    except OSError as e:  # launchctl / systemctl missing or not executable
        raise SchedulerInstallFailed(f"cannot run {argv[0]}: {e}") from e


class SchedulerInstallFailed(InfrastructureError):
    """The unit was written but the OS refused to enable it; nothing is left
    behind, so ``installed()`` stays False and the CLI exits nonzero."""


def _plist_env(env: Mapping[str, str]) -> str:
    return "".join(
        f"\n    <key>{escape(k)}</key>\n    <string>{escape(v)}</string>"
        for k, v in sorted(env.items())
    )


def _service_value(value: str) -> str:
    """Quote for ``Environment="K=V"`` (systemd.syntax: backslash and quote
    escaped inside quotes; ``%`` doubled so specifiers stay literal). A
    newline or NUL cannot be carried and is refused."""
    if "\n" in value or "\0" in value:
        raise SchedulerInstallFailed(f"cannot persist {value!r} into a unit file")
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")


def _service_env(env: Mapping[str, str]) -> str:
    return "".join(
        f'\nEnvironment="{k}={_service_value(v)}"' for k, v in sorted(env.items())
    )


class SchedulerInstaller(Protocol):
    def install(
        self,
        *,
        interval_sec: int,
        dry_run: bool = False,
        env: Mapping[str, str] | None = None,
    ) -> list[str]:
        """Write and enable the unit. ``env`` is persisted into it: the tick
        runs in a fresh service environment, so the definitions and state
        roots chosen at install time (CHORES_HOME, XDG_*) must travel with it.
        """
        ...

    def uninstall(self) -> list[str]: ...

    def installed(self) -> bool: ...

    def installed_interval(self) -> int | None: ...


class LaunchdInstaller:
    def __init__(self, *, home: Path, uid: int, run: RunFn = _run_subprocess) -> None:
        self.plist = home / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
        self._domain = f"gui/{uid}"
        self._run = run

    def install(
        self,
        *,
        interval_sec: int,
        dry_run: bool = False,
        env: Mapping[str, str] | None = None,
    ) -> list[str]:
        text = _PLIST.format(
            label=LAUNCHD_LABEL, interval=interval_sec, env=_plist_env(env or {})
        )
        if dry_run:
            return [
                f"would write {self.plist}",
                f"would launchctl bootstrap {self._domain}",
            ]
        try:
            self.plist.parent.mkdir(parents=True, exist_ok=True)
            self.plist.write_text(text)
        except OSError as e:  # permissions, disk: nothing was loaded
            _remove_quietly(self.plist)
            raise SchedulerInstallFailed(f"cannot write {self.plist}: {e}") from e
        try:
            self._run(["launchctl", "bootout", f"{self._domain}/{LAUNCHD_LABEL}"])
            rc = self._run(["launchctl", "bootstrap", self._domain, str(self.plist)])
        except SchedulerInstallFailed:
            self.plist.unlink(missing_ok=True)  # nothing half-installed
            raise
        if rc != 0:
            # bootstrap can fail after loading part of the job: unload the
            # label before the plist goes, so nothing orphaned keeps running
            self._run(["launchctl", "bootout", f"{self._domain}/{LAUNCHD_LABEL}"])
            self.plist.unlink(missing_ok=True)
            raise SchedulerInstallFailed(
                f"launchctl bootstrap {self._domain} failed (exit {rc}); "
                f"booted out and removed {self.plist}"
            )
        return [
            f"wrote {self.plist}",
            f"bootstrapped {LAUNCHD_LABEL} every {interval_sec}s",
        ]

    def uninstall(self) -> list[str]:
        target = f"{self._domain}/{LAUNCHD_LABEL}"
        rc = self._run(["launchctl", "bootout", target])
        # bootout is nonzero when the job was not loaded (fine, idempotent)
        # and when it could not be unloaded (not fine): `print` tells them
        # apart -- it succeeds only while the job is still loaded.
        if rc != 0 and self._run(["launchctl", "print", target]) == 0:
            raise SchedulerInstallFailed(
                f"launchctl bootout {target} failed (exit {rc}) and the job is "
                f"still loaded; {self.plist} left in place"
            )
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

    def install(
        self,
        *,
        interval_sec: int,
        dry_run: bool = False,
        env: Mapping[str, str] | None = None,
    ) -> list[str]:
        if dry_run:
            return [
                f"would write {self.timer} and its service",
                "would enable the timer",
            ]
        try:
            self.unit_dir.mkdir(parents=True, exist_ok=True)
            (self.unit_dir / f"{SYSTEMD_UNIT}.service").write_text(
                _SERVICE.format(env=_service_env(env or {}))
            )
            self.timer.write_text(_TIMER.format(interval=interval_sec))
        except OSError as e:  # permissions, disk: nothing was enabled
            for name in (f"{SYSTEMD_UNIT}.timer", f"{SYSTEMD_UNIT}.service"):
                _remove_quietly(self.unit_dir / name)
            raise SchedulerInstallFailed(f"cannot write {self.unit_dir}: {e}") from e
        try:
            reload_rc = self._run(["systemctl", "--user", "daemon-reload"])
            if reload_rc != 0:
                # enable would act on stale cached units, not the files
                # just written: treat it as the install failing
                raise SchedulerInstallFailed(
                    f"systemctl --user daemon-reload failed (exit {reload_rc})"
                )
            rc = self._run(
                ["systemctl", "--user", "enable", "--now", f"{SYSTEMD_UNIT}.timer"]
            )
        except SchedulerInstallFailed:
            for name in (f"{SYSTEMD_UNIT}.timer", f"{SYSTEMD_UNIT}.service"):
                (self.unit_dir / name).unlink(missing_ok=True)
            self._run(["systemctl", "--user", "daemon-reload"])
            raise
        if rc != 0:
            # enable --now can fail after enabling or starting: stop and
            # disable first so no active timer or .wants link is left behind
            self._run(
                ["systemctl", "--user", "disable", "--now", f"{SYSTEMD_UNIT}.timer"]
            )
            for name in (f"{SYSTEMD_UNIT}.timer", f"{SYSTEMD_UNIT}.service"):
                (self.unit_dir / name).unlink(missing_ok=True)
            self._run(["systemctl", "--user", "daemon-reload"])
            raise SchedulerInstallFailed(
                f"systemctl --user enable --now {SYSTEMD_UNIT}.timer failed "
                f"(exit {rc}); disabled and removed the unit files"
            )
        return [
            f"wrote {self.timer}",
            f"enabled {SYSTEMD_UNIT}.timer every {interval_sec}s",
        ]

    def uninstall(self) -> list[str]:
        timer = f"{SYSTEMD_UNIT}.timer"
        rc = self._run(["systemctl", "--user", "disable", "--now", timer])
        # disable is nonzero for an unknown unit (fine) and for a unit it
        # could not stop (not fine): is-active succeeds only in the latter.
        if rc != 0 and self._run(["systemctl", "--user", "is-active", timer]) == 0:
            raise SchedulerInstallFailed(
                f"systemctl --user disable --now {timer} failed (exit {rc}) and "
                "the timer is still active; unit files left in place"
            )
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
