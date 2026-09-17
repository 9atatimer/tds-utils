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

from chores.adapters.fs_store import UnsafeStatePath, read_nofollow, write_nofollow
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
# `bash -c`, not `-lc`: a login shell would source /etc/profile and the
# user's profile, which may rebuild PATH and drop the tiers above.
Environment=PATH=%h/.tds/dist/current/bin:%h/.tds/release/bin:%h/workplace/tds-utils/bin:%h/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/bin/bash -c 'exec chores tick'
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


def _put_back(path: Path, previous: str | None) -> None:
    """Undo one unit write: restore the text a prior install left there, or
    remove the file when this invocation created it. Best effort: the
    failure being reported is the install, not the undo."""
    if previous is None:
        _remove_quietly(path)
        return
    try:
        write_nofollow(path, previous)
    except (OSError, UnsafeStatePath):
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
            previous = read_nofollow(self.plist)  # a prior install's, to put back
            write_nofollow(self.plist, text)  # a planted symlink is refused
        except (OSError, UnsafeStatePath) as e:
            # Nothing was loaded and nothing of ours was written: whatever
            # sits at the path (a symlink, a plist a previous install left)
            # was not created by this invocation and is left as found.
            raise SchedulerInstallFailed(f"cannot write {self.plist}: {e}") from e
        try:
            self._run(["launchctl", "bootout", f"{self._domain}/{LAUNCHD_LABEL}"])
            rc = self._run(["launchctl", "bootstrap", self._domain, str(self.plist)])
        except SchedulerInstallFailed:
            self._rollback(previous)  # a reinstall may have had the job loaded
            raise
        if rc != 0:
            # bootstrap can fail after loading part of the job: unload the
            # label before the plist goes, so nothing orphaned keeps running
            self._rollback(previous)
            undone = "restored the previous" if previous is not None else "removed"
            raise SchedulerInstallFailed(
                f"launchctl bootstrap {self._domain} failed (exit {rc}); "
                f"booted out and {undone} {self.plist}"
            )
        return [
            f"wrote {self.plist}",
            f"bootstrapped {LAUNCHD_LABEL} every {interval_sec}s",
        ]

    def _rollback(self, previous: str | None) -> None:
        """Boot the label out (best effort) and undo the plist write: the
        prior install's plist goes back and is bootstrapped again, or the
        plist this invocation created is removed. Nothing loaded may outlive
        a plist that is gone, and a failed reinstall leaves the old
        configuration running. Only reached after the write succeeded."""
        try:
            self._run(["launchctl", "bootout", f"{self._domain}/{LAUNCHD_LABEL}"])
        except SchedulerInstallFailed:
            pass  # launchctl itself is missing: nothing can be loaded
        _put_back(self.plist, previous)
        if previous is not None:
            try:
                self._run(["launchctl", "bootstrap", self._domain, str(self.plist)])
            except SchedulerInstallFailed:
                pass

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
        units = (
            (
                self.unit_dir / f"{SYSTEMD_UNIT}.service",
                _SERVICE.format(env=_service_env(env or {})),
            ),
            (self.timer, _TIMER.format(interval=interval_sec)),
        )
        written: dict[Path, str | None] = {}  # what THIS invocation wrote -> before
        try:
            self.unit_dir.mkdir(parents=True, exist_ok=True)
            for path, text in units:
                previous = read_nofollow(path)  # a prior install's, to put back
                write_nofollow(path, text)  # a planted symlink is refused
                written[path] = previous
        except (OSError, UnsafeStatePath) as e:
            # A path whose write was refused (a symlink, an unwritable file)
            # was not touched here and is left as found; a unit written
            # before it is undone, since the pair is only valid together.
            self._rollback(written)
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
            self._rollback(written)
            raise
        if rc != 0:
            self._rollback(written)
            undone = (
                "restored the previous unit files"
                if any(v is not None for v in written.values())
                else "removed the unit files"
            )
            raise SchedulerInstallFailed(
                f"systemctl --user enable --now {SYSTEMD_UNIT}.timer failed "
                f"(exit {rc}); disabled and {undone}"
            )
        return [
            f"wrote {self.timer}",
            f"enabled {SYSTEMD_UNIT}.timer every {interval_sec}s",
        ]

    def _rollback(self, written: Mapping[Path, str | None]) -> None:
        """The one way out of a failed install, whatever failed: stop and
        disable the timer (a reinstall may have found one active, and enable
        --now may have half-started the new one), undo each unit write this
        invocation made (the prior install's text goes back, a file created
        here is removed), reload, and re-enable a restored timer. Nothing
        loaded may outlive files that are gone, a failed reinstall leaves the
        old configuration running, and nothing this invocation did not write
        is touched: a failure before the first write changes nothing."""
        if not written:
            return
        try:
            self._run(
                ["systemctl", "--user", "disable", "--now", f"{SYSTEMD_UNIT}.timer"]
            )
        except SchedulerInstallFailed:
            pass  # systemctl itself is missing: nothing can be loaded
        for path, previous in written.items():
            _put_back(path, previous)
        try:
            self._run(["systemctl", "--user", "daemon-reload"])
            if written.get(self.timer) is not None:  # the prior timer is back
                self._run(
                    ["systemctl", "--user", "enable", "--now", f"{SYSTEMD_UNIT}.timer"]
                )
        except SchedulerInstallFailed:
            pass

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
