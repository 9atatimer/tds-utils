"""The composition root: a CLI invocation with no injected Deps builds real
adapters from the environment (the bug this pins: ensure_object had
pre-filled obj, so wiring never ran outside tests)."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from chores.cli.main import main
from chores.cli.wiring import resolve_paths

from .test_runner import COMMAND, write_home


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
