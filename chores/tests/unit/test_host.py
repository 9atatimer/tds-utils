"""Host adapters: battery detection from the Linux power-supply tree."""

from __future__ import annotations

from pathlib import Path


def test_linux_battery_detection_covers_named_mains_and_battery_status(
    tmp_path: Path,
) -> None:
    from chores.adapters.host import linux_on_battery

    def supply(name: str, **files: str) -> None:
        d = tmp_path / name
        d.mkdir(parents=True, exist_ok=True)
        for k, v in files.items():
            (d / k).write_text(v + "\n")

    assert linux_on_battery(tmp_path / "missing") is False
    supply("ADP1", type="Mains", online="0")
    supply("BAT0", type="Battery", status="Discharging")
    assert linux_on_battery(tmp_path) is True
    supply("ADP1", type="Mains", online="1")
    assert linux_on_battery(tmp_path) is False  # mains decides over the battery
    import shutil

    shutil.rmtree(tmp_path / "ADP1")
    assert linux_on_battery(tmp_path) is True  # no mains: battery status decides
    supply("BAT0", type="Battery", status="Charging")
    assert linux_on_battery(tmp_path) is False
