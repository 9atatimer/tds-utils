"""chores install / uninstall (CHORES.DESIGN.md Subsystem 2, install-time only)."""

from __future__ import annotations

from pathlib import Path

import pytest

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


def test_installer_reports_a_failed_bootstrap(tmp_path: Path) -> None:
    from chores.adapters.scheduler import SchedulerInstallFailed

    inst = LaunchdInstaller(
        home=tmp_path, uid=1, run=lambda argv: 1 if argv[1] == "bootstrap" else 0
    )
    with pytest.raises(SchedulerInstallFailed, match="bootstrap"):
        inst.install(interval_sec=60)
    assert inst.installed() is False


def test_systemd_service_names_the_runtime_path(tmp_path: Path) -> None:
    from chores.adapters.scheduler import SystemdInstaller

    inst = SystemdInstaller(home=tmp_path, run=lambda argv: 0)
    inst.install(interval_sec=60)
    service = (
        tmp_path / ".config" / "systemd" / "user" / "chores-tick.service"
    ).read_text()
    assert "Environment=PATH=%h/.tds/dist/current/bin" in service


def test_failed_scheduler_enable_raises_and_leaves_nothing_behind(
    tmp_path: Path,
) -> None:
    from chores.adapters.scheduler import SchedulerInstallFailed, SystemdInstaller

    def enable_fails(argv: list[str]) -> int:
        return 1 if "enable" in argv or "bootstrap" in argv else 0

    launchd = LaunchdInstaller(home=tmp_path / "mac", uid=501, run=enable_fails)
    with pytest.raises(SchedulerInstallFailed):
        launchd.install(interval_sec=60)
    assert launchd.installed() is False
    systemd = SystemdInstaller(home=tmp_path / "linux", run=enable_fails)
    with pytest.raises(SchedulerInstallFailed):
        systemd.install(interval_sec=60)
    assert systemd.installed() is False


def test_systemd_path_includes_the_fresh_clone_tier(tmp_path: Path) -> None:
    from chores.adapters.scheduler import SystemdInstaller

    inst = SystemdInstaller(home=tmp_path, run=lambda argv: 0)
    inst.install(interval_sec=60)
    service = (
        tmp_path / ".config" / "systemd" / "user" / "chores-tick.service"
    ).read_text()
    assert "%h/workplace/tds-utils/bin" in service


def test_scheduler_units_persist_the_roots_chosen_at_install(tmp_path: Path) -> None:
    from chores.adapters.scheduler import SystemdInstaller

    env = {"CHORES_HOME": "/Users/t/workplace/tds-internal/ops/chores"}
    launchd = LaunchdInstaller(home=tmp_path / "mac", uid=501, run=lambda a: 0)
    launchd.install(interval_sec=60, env={**env, "XDG_STATE_HOME": "/a b/c"})
    plist = launchd.plist.read_text()
    assert "<key>CHORES_HOME</key>" in plist and env["CHORES_HOME"] in plist
    assert "<key>XDG_STATE_HOME</key>\n    <string>/a b/c</string>" in plist
    systemd = SystemdInstaller(home=tmp_path / "linux", run=lambda a: 0)
    systemd.install(interval_sec=60, env={**env, "XDG_STATE_HOME": "/a b/c"})
    service = (systemd.unit_dir / "chores-tick.service").read_text()
    assert f'Environment="CHORES_HOME={env["CHORES_HOME"]}"' in service
    assert 'Environment="XDG_STATE_HOME=/a b/c"' in service
    assert "Environment=PATH=" in service


def test_systemd_environment_values_are_escaped(tmp_path: Path) -> None:
    from chores.adapters.scheduler import SchedulerInstallFailed, SystemdInstaller

    inst = SystemdInstaller(home=tmp_path, run=lambda a: 0)
    inst.install(interval_sec=60, env={"CHORES_HOME": '/h/"odd"\\100%'})
    service = (inst.unit_dir / "chores-tick.service").read_text()
    assert 'Environment="CHORES_HOME=/h/\\"odd\\"\\\\100%%"' in service
    with pytest.raises(SchedulerInstallFailed):
        inst.install(interval_sec=60, env={"CHORES_HOME": "/a\nb"})


def test_uninstall_fails_loudly_when_the_os_keeps_the_unit_loaded(
    tmp_path: Path,
) -> None:
    from chores.adapters.scheduler import SchedulerInstallFailed, SystemdInstaller

    def stuck(argv: list[str]) -> int:
        if argv[:2] == ["launchctl", "bootout"] or "disable" in argv:
            return 1  # could not unload / stop
        return 0  # `launchctl print` / `is-active`: still loaded

    def not_loaded(argv: list[str]) -> int:
        ok = ("bootstrap", "enable", "daemon-reload")
        return 0 if any(word in argv for word in ok) else 1

    launchd = LaunchdInstaller(home=tmp_path / "mac", uid=1, run=stuck)
    launchd.install(interval_sec=60)
    with pytest.raises(SchedulerInstallFailed, match="still loaded"):
        launchd.uninstall()
    assert launchd.installed() is True  # the plist is left in place
    launchd = LaunchdInstaller(home=tmp_path / "mac2", uid=1, run=not_loaded)
    launchd.install(interval_sec=60)
    launchd.uninstall()  # bootout nonzero but not loaded: idempotent
    assert launchd.installed() is False
    systemd = SystemdInstaller(home=tmp_path / "linux", run=stuck)
    systemd.install(interval_sec=60)
    with pytest.raises(SchedulerInstallFailed, match="still active"):
        systemd.uninstall()
    assert systemd.installed() is True
    systemd = SystemdInstaller(home=tmp_path / "linux2", run=not_loaded)
    systemd.install(interval_sec=60)
    systemd.uninstall()
    assert systemd.installed() is False


def test_a_missing_scheduler_command_is_a_controlled_failure(tmp_path: Path) -> None:
    from chores.adapters.scheduler import (
        SchedulerInstallFailed,
        SystemdInstaller,
        _run_subprocess,
    )

    with pytest.raises(SchedulerInstallFailed, match="cannot run"):
        _run_subprocess(["/definitely/not/launchctl", "print"])

    def missing(argv: list[str]) -> int:
        raise SchedulerInstallFailed(f"cannot run {argv[0]}: not found")

    launchd = LaunchdInstaller(home=tmp_path / "mac", uid=1, run=missing)
    with pytest.raises(SchedulerInstallFailed, match="cannot run"):
        launchd.install(interval_sec=60)
    assert launchd.installed() is False  # the written plist was removed
    systemd = SystemdInstaller(home=tmp_path / "linux", run=missing)
    with pytest.raises(SchedulerInstallFailed, match="cannot run"):
        systemd.install(interval_sec=60)
    assert systemd.installed() is False
    assert not (systemd.unit_dir / "chores-tick.service").exists()


def test_systemd_install_fails_when_daemon_reload_fails(tmp_path: Path) -> None:
    from chores.adapters.scheduler import SchedulerInstallFailed, SystemdInstaller

    calls: list[list[str]] = []

    def reload_fails(argv: list[str]) -> int:
        calls.append(argv)
        return 1 if "daemon-reload" in argv and len(calls) == 1 else 0

    inst = SystemdInstaller(home=tmp_path, run=reload_fails)
    with pytest.raises(SchedulerInstallFailed, match="daemon-reload"):
        inst.install(interval_sec=60)
    assert inst.installed() is False
    assert not (inst.unit_dir / "chores-tick.service").exists()
    assert calls[-1] == ["systemctl", "--user", "daemon-reload"]  # reloaded again


def test_failed_install_unloads_what_it_loaded(tmp_path: Path) -> None:
    from chores.adapters.scheduler import SchedulerInstallFailed, SystemdInstaller

    calls: list[list[str]] = []

    def enable_fails(argv: list[str]) -> int:
        calls.append(argv)
        return 1 if "bootstrap" in argv or "enable" in argv else 0

    launchd = LaunchdInstaller(home=tmp_path / "mac", uid=1, run=enable_fails)
    with pytest.raises(SchedulerInstallFailed, match="booted out"):
        launchd.install(interval_sec=60)
    assert calls[-1][:2] == ["launchctl", "bootout"] and not launchd.installed()
    calls.clear()
    systemd = SystemdInstaller(home=tmp_path / "linux", run=enable_fails)
    with pytest.raises(SchedulerInstallFailed, match="disabled and removed"):
        systemd.install(interval_sec=60)
    assert ["systemctl", "--user", "disable", "--now", "chores-tick.timer"] in calls
    assert calls[-1] == ["systemctl", "--user", "daemon-reload"]
    assert not systemd.installed()


def test_unwritable_unit_paths_are_a_controlled_install_failure(
    tmp_path: Path,
) -> None:
    from chores.adapters.scheduler import SchedulerInstallFailed, SystemdInstaller

    blocker = tmp_path / "mac" / "Library"
    blocker.parent.mkdir()
    blocker.write_text("a file where a directory must go")
    launchd = LaunchdInstaller(home=tmp_path / "mac", uid=1, run=lambda a: 0)
    with pytest.raises(SchedulerInstallFailed, match="cannot write"):
        launchd.install(interval_sec=60)
    blocker = tmp_path / "linux" / ".config"
    blocker.parent.mkdir()
    blocker.write_text("same")
    systemd = SystemdInstaller(home=tmp_path / "linux", run=lambda a: 0)
    with pytest.raises(SchedulerInstallFailed, match="cannot write"):
        systemd.install(interval_sec=60)


def test_unit_files_are_written_no_follow(tmp_path: Path) -> None:
    from chores.adapters.scheduler import SchedulerInstallFailed, SystemdInstaller

    outside = tmp_path / "outside"
    outside.mkdir()
    agents = tmp_path / "mac" / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    (agents / "com.tds.chores.tick.plist").symlink_to(outside / "plist")
    launchd = LaunchdInstaller(home=tmp_path / "mac", uid=1, run=lambda a: 0)
    with pytest.raises(SchedulerInstallFailed, match="symlink"):
        launchd.install(interval_sec=60)
    assert not (outside / "plist").exists()
    units = tmp_path / "linux" / ".config" / "systemd" / "user"
    units.mkdir(parents=True)
    (units / "chores-tick.timer").symlink_to(outside / "timer")
    systemd = SystemdInstaller(home=tmp_path / "linux", run=lambda a: 0)
    with pytest.raises(SchedulerInstallFailed, match="symlink"):
        systemd.install(interval_sec=60)
    assert not (outside / "timer").exists()
    assert not (units / "chores-tick.service").exists()  # cleaned up


def test_systemd_service_runs_a_plain_shell_so_the_unit_path_holds(
    tmp_path: Path,
) -> None:
    from chores.adapters.scheduler import SystemdInstaller

    inst = SystemdInstaller(home=tmp_path, run=lambda a: 0)
    inst.install(interval_sec=60)
    service = (inst.unit_dir / "chores-tick.service").read_text()
    exec_line = next(line for line in service.splitlines() if "ExecStart" in line)
    assert exec_line == "ExecStart=/bin/bash -c 'exec chores tick'"
    assert "-l" not in exec_line  # a login shell could rebuild PATH


def test_a_failed_reinstall_never_leaves_the_old_timer_loaded(tmp_path: Path) -> None:
    """Whatever fails during a reinstall (here: the reload), the rollback
    stops and disables the timer before the unit files go, so nothing
    loaded outlives files that are gone."""
    from chores.adapters.scheduler import SchedulerInstallFailed, SystemdInstaller

    calls: list[list[str]] = []

    def reload_fails_once(argv: list[str]) -> int:
        calls.append(argv)
        reloads = sum(1 for c in calls if "daemon-reload" in c)
        return 1 if "daemon-reload" in argv and reloads == 1 else 0

    inst = SystemdInstaller(home=tmp_path, run=reload_fails_once)
    with pytest.raises(SchedulerInstallFailed, match="daemon-reload"):
        inst.install(interval_sec=60)
    assert ["systemctl", "--user", "disable", "--now", "chores-tick.timer"] in calls
    assert inst.installed() is False
    launchd_calls: list[list[str]] = []

    def launchctl_missing(argv: list[str]) -> int:
        launchd_calls.append(argv)
        raise SchedulerInstallFailed("cannot run launchctl")

    mac = LaunchdInstaller(home=tmp_path / "mac", uid=1, run=launchctl_missing)
    with pytest.raises(SchedulerInstallFailed):
        mac.install(interval_sec=60)
    assert mac.installed() is False


def test_a_refused_unit_write_leaves_what_it_found(tmp_path: Path) -> None:
    """An installer removes only what this invocation wrote. A path whose
    no-follow write was refused (a symlink someone planted, or a unit a
    previous install left) is preserved, and when nothing was written nothing
    is disabled either."""
    from chores.adapters.scheduler import SchedulerInstallFailed, SystemdInstaller

    outside = tmp_path / "outside"
    outside.mkdir()
    agents = tmp_path / "mac" / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    plist = agents / "com.tds.chores.tick.plist"
    plist.symlink_to(outside / "plist")
    mac_calls: list[list[str]] = []
    launchd = LaunchdInstaller(
        home=tmp_path / "mac", uid=1, run=lambda a: mac_calls.append(a) or 0
    )
    with pytest.raises(SchedulerInstallFailed, match="symlink"):
        launchd.install(interval_sec=60)
    assert plist.is_symlink() and mac_calls == []  # preserved, nothing booted out
    units = tmp_path / "linux" / ".config" / "systemd" / "user"
    units.mkdir(parents=True)
    service = units / "chores-tick.service"
    service.symlink_to(outside / "service")
    calls: list[list[str]] = []
    systemd = SystemdInstaller(
        home=tmp_path / "linux", run=lambda a: calls.append(a) or 0
    )
    with pytest.raises(SchedulerInstallFailed, match="symlink"):
        systemd.install(interval_sec=60)
    assert service.is_symlink() and calls == []  # first write refused: untouched
    assert not systemd.timer.exists()
    service.unlink()
    systemd.timer.symlink_to(outside / "timer")
    with pytest.raises(SchedulerInstallFailed, match="symlink"):
        systemd.install(interval_sec=60)
    assert systemd.timer.is_symlink()  # the refused path is preserved
    assert not service.exists()  # the unit this invocation wrote is gone
    assert ["systemctl", "--user", "disable", "--now", "chores-tick.timer"] in calls


def test_a_failed_reinstall_restores_the_previous_units(tmp_path: Path) -> None:
    """A reinstall that fails after overwriting a unit puts the prior
    install's text back and loads it again, so the old configuration keeps
    running rather than vanishing."""
    from chores.adapters.scheduler import SchedulerInstallFailed, SystemdInstaller

    calls: list[list[str]] = []

    def enable_fails_after_first(argv: list[str]) -> int:
        calls.append(argv)
        enables = sum(1 for c in calls if "enable" in c)
        return 1 if "enable" in argv and enables == 2 else 0

    inst = SystemdInstaller(home=tmp_path, run=enable_fails_after_first)
    inst.install(interval_sec=60)
    with pytest.raises(SchedulerInstallFailed, match="restored the previous"):
        inst.install(interval_sec=120)
    assert inst.installed_interval() == 60  # the prior timer is back
    assert "CHORES_HOME" not in (inst.unit_dir / "chores-tick.service").read_text()
    assert [c for c in calls if "enable" in c][-1][-1] == "chores-tick.timer"
    assert calls[-2:] == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", "chores-tick.timer"],
    ]
    mac_calls: list[list[str]] = []

    def bootstrap_fails_after_first(argv: list[str]) -> int:
        mac_calls.append(argv)
        boots = sum(1 for c in mac_calls if "bootstrap" in c)
        return 1 if "bootstrap" in argv and boots == 2 else 0

    mac = LaunchdInstaller(
        home=tmp_path / "mac", uid=1, run=bootstrap_fails_after_first
    )
    mac.install(interval_sec=60)
    with pytest.raises(SchedulerInstallFailed, match="restored the previous"):
        mac.install(interval_sec=120)
    assert mac.installed_interval() == 60
    assert mac_calls[-1][:2] == ["launchctl", "bootstrap"]  # the old plist reloaded


def test_installed_interval_reads_the_start_interval_key(tmp_path: Path) -> None:
    """The interval is read from its own key, not from whichever <integer>
    happens to come first -- the plist template may grow another one."""
    inst = LaunchdInstaller(home=tmp_path, uid=501, run=Recorder())
    inst.install(interval_sec=45)
    text = inst.plist.read_text()
    inst.plist.write_text(
        text.replace(
            "<key>Label</key>",
            "<key>Nice</key>\n  <integer>7</integer>\n  <key>Label</key>",
        )
    )
    assert inst.installed_interval() == 45
