"""chores install / uninstall (CHORES.DESIGN.md Subsystem 2, install-time only)."""

from __future__ import annotations

from pathlib import Path

from chores.adapters.scheduler import LaunchdInstaller, SystemdInstaller, installer_for


class Recorder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> int:
        self.calls.append(argv)
        return 0


def test_launchd_writes_a_plist_with_the_interval_and_bootstraps(
    tmp_path: Path,
) -> None:
    rec = Recorder()
    inst = LaunchdInstaller(home=tmp_path, uid=501, run=rec)
    assert inst.installed() is False
    actions = inst.install(interval_sec=45)
    plist = tmp_path / "Library" / "LaunchAgents" / "com.tds.chores.tick.plist"
    text = plist.read_text()
    assert (
        "<integer>45</integer>" in text and "exec chores tick" in text and "-lc" in text
    )
    assert "<key>Label</key>" in text and "com.tds.chores.tick" in text
    assert rec.calls[0][:2] == ["launchctl", "bootout"]  # idempotent: unload first
    assert rec.calls[1] == ["launchctl", "bootstrap", "gui/501", str(plist)]
    assert inst.installed() is True and inst.installed_interval() == 45
    assert any("wrote" in a for a in actions)


def test_launchd_dry_run_touches_nothing(tmp_path: Path) -> None:
    rec = Recorder()
    actions = LaunchdInstaller(home=tmp_path, uid=501, run=rec).install(
        interval_sec=60, dry_run=True
    )
    assert rec.calls == [] and not (tmp_path / "Library").exists()
    assert any("would write" in a for a in actions)


def test_launchd_uninstall_boots_out_and_removes(tmp_path: Path) -> None:
    rec = Recorder()
    inst = LaunchdInstaller(home=tmp_path, uid=501, run=rec)
    inst.install(interval_sec=60)
    inst.uninstall()
    assert rec.calls[-1] == ["launchctl", "bootout", "gui/501/com.tds.chores.tick"]
    assert inst.installed() is False


def test_systemd_writes_service_and_timer_and_enables(tmp_path: Path) -> None:
    rec = Recorder()
    inst = SystemdInstaller(home=tmp_path, run=rec)
    inst.install(interval_sec=90)
    unit_dir = tmp_path / ".config" / "systemd" / "user"
    timer = (unit_dir / "chores-tick.timer").read_text()
    service = (unit_dir / "chores-tick.service").read_text()
    assert "OnUnitActiveSec=90s" in timer and "chores tick" in service
    assert ["systemctl", "--user", "daemon-reload"] in rec.calls
    assert ["systemctl", "--user", "enable", "--now", "chores-tick.timer"] in rec.calls
    assert inst.installed() is True and inst.installed_interval() == 90
    inst.uninstall()
    assert ["systemctl", "--user", "disable", "--now", "chores-tick.timer"] in rec.calls
    assert inst.installed() is False


def test_installer_for_picks_by_platform(tmp_path: Path) -> None:
    assert isinstance(
        installer_for("Darwin", home=tmp_path, uid=1, run=Recorder()), LaunchdInstaller
    )
    assert isinstance(
        installer_for("Linux", home=tmp_path, uid=1, run=Recorder()), SystemdInstaller
    )
    assert installer_for("Windows", home=tmp_path, uid=1, run=Recorder()) is None
