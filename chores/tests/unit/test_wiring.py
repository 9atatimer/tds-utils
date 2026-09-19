"""The composition root: a CLI invocation with no injected Deps builds real
adapters from the environment (the bug this pins: ensure_object had
pre-filled obj, so wiring never ran outside tests), and the three roots it
resolves -- canonical, non-overlapping, and written no-follow.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from chores.cli.main import main
from chores.cli.wiring import resolve_paths

from ._harness import COMMAND, write_home


def test_cli_without_obj_uses_the_composition_root(tmp_path: Path) -> None:
    home = tmp_path / "defs"
    write_home(home, chores={"tidy": COMMAND})
    env = {
        "HOME": str(tmp_path / "h"),
        "CHORES_HOME": str(home),
        "XDG_STATE_HOME": str(tmp_path / "state"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "PATH": "/usr/bin:/bin",
    }
    runner = CliRunner(env=env)
    result = runner.invoke(main, ["list"], catch_exceptions=False)
    assert result.exit_code == 0 and "tidy" in result.output
    result = runner.invoke(main, ["status", "--json"], catch_exceptions=False)
    view = json.loads(result.output)
    assert [c["name"] for c in view["chores"]] == ["tidy"]
    assert (tmp_path / "state" / "chores").is_dir()


def test_resolve_paths_honours_env(tmp_path: Path) -> None:
    paths = resolve_paths({"HOME": "/h", "CHORES_HOME": "/c", "XDG_STATE_HOME": "/s"})
    assert paths.chores_home == "/c" and paths.state_dir == "/s/chores"
    assert paths.data_dir == "/h/.local/share/chores"
    default = resolve_paths({"HOME": "/h"})
    assert (
        default.chores_home == "/h/.config/chores"
        and default.state_dir == "/h/.local/state/chores"
    )


def test_overlapping_data_and_state_roots_are_refused(tmp_path: Path) -> None:
    from chores.application.paths import OverlappingRoots, Paths
    from chores.cli.wiring import resolve_paths

    with pytest.raises(OverlappingRoots):
        Paths(
            str(tmp_path / "home"),
            str(tmp_path / "state"),
            str(tmp_path / "state" / "d"),
        )
    with pytest.raises(OverlappingRoots):
        Paths(
            str(tmp_path / "home"), str(tmp_path / "d" / "state"), str(tmp_path / "d")
        )
    with pytest.raises(OverlappingRoots):
        resolve_paths(
            {
                "HOME": str(tmp_path),
                "XDG_STATE_HOME": str(tmp_path / "st"),
                "XDG_DATA_HOME": str(tmp_path / "st" / "chores" / "data"),
            }
        )


def test_roots_are_resolved_so_a_symlinked_state_dir_cannot_be_reached(
    tmp_path: Path,
) -> None:
    from chores.cli.wiring import resolve_paths

    real = tmp_path / "real-state"
    real.mkdir()
    link = tmp_path / "link-state"
    link.symlink_to(real)
    paths = resolve_paths({"HOME": str(tmp_path), "XDG_STATE_HOME": str(link)})
    assert paths.state_dir == str(real / "chores")
    assert str(real / "chores") in paths.forbidden_for_cwd()


def test_empty_xdg_values_are_unset_not_the_working_directory(tmp_path: Path) -> None:
    from chores.cli.wiring import resolve_paths

    paths = resolve_paths(
        {"HOME": str(tmp_path), "XDG_STATE_HOME": "", "XDG_DATA_HOME": ""}
    )
    assert paths.state_dir == str(tmp_path / ".local" / "state" / "chores")
    assert paths.data_dir == str(tmp_path / ".local" / "share" / "chores")


def test_home_pointer_and_spawn_log_are_written_no_follow(tmp_path: Path) -> None:
    from chores.adapters.fs_store import UnsafeStatePath
    from chores.application.paths import Paths
    from chores.cli.wiring import _launch_factory, remember_home

    outside = tmp_path / "outside"
    outside.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    (state / "home").symlink_to(outside / "pointer")
    paths = Paths(str(tmp_path / "home"), str(state), str(tmp_path / "data"))
    with pytest.raises(UnsafeStatePath):
        remember_home(paths)
    assert not (outside / "pointer").exists()
    (state / "spawn.log").symlink_to(outside / "spawn")
    with pytest.raises(UnsafeStatePath):
        _launch_factory(state)("tidy")
    assert not (outside / "spawn").exists()


def test_state_and_definitions_roots_may_not_contain_each_other(tmp_path: Path) -> None:
    from chores.application.paths import OverlappingRoots, Paths

    with pytest.raises(OverlappingRoots, match="definitions"):
        Paths(
            str(tmp_path / "cfg" / "chores"), str(tmp_path / "cfg"), str(tmp_path / "d")
        )
    with pytest.raises(OverlappingRoots):
        Paths(str(tmp_path / "s" / "home"), str(tmp_path / "s"), str(tmp_path / "d"))
    Paths(
        str(tmp_path / "h"), str(tmp_path / "s"), str(tmp_path / "d")
    )  # distinct: fine
