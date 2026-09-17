"""The composition root: real adapters wired to the ports, paths resolved
from the environment. The only module that knows every adapter."""

from __future__ import annotations

import os
import platform
import secrets
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from chores.adapters.definitions import DefinitionsLoader
from chores.adapters.fs_store import FsRunStore, FsWorkspaces
from chores.adapters.host import (
    DesktopNotifier,
    SocketNetwork,
    SystemClock,
    SystemPower,
)
from chores.adapters.process import SubprocessRunner
from chores.adapters.registry import BackendCatalog
from chores.adapters.scheduler import installer_for
from chores.adapters.secrets import OpSecrets
from chores.application.deps import Deps
from chores.application.paths import Paths
from chores.ports.definitions import Definitions

HOME_POINTER = "home"  # <state dir>/home: the CHORES_HOME `chores install` saw


def resolve_paths(env: dict[str, str] | None = None) -> Paths:
    """CHORES_HOME from the environment, else from the pointer `chores
    install` left in the state dir (so launchd agents and the menu-bar
    monitor, which see no shell exports, use the installed herd), else the
    XDG default."""
    e = os.environ if env is None else env
    # `or`, not a default argument: an empty exported value is unset, else
    # Path("") is the current directory and state lands in the working tree.
    home = Path(e.get("HOME") or "~").expanduser()
    state = (
        Path(e.get("XDG_STATE_HOME") or home / ".local" / "state").expanduser()
        / "chores"
    )
    chores_home = Path(
        e.get("CHORES_HOME") or _pointer(state) or home / ".config" / "chores"
    )
    chores_home = chores_home.expanduser()
    data = (
        Path(e.get("XDG_DATA_HOME") or home / ".local" / "share").expanduser()
        / "chores"
    )
    # realpath, not resolve(): the same canonicalisation the loader applies to
    # every chore cwd, so containment compares like with like.
    return Paths(
        chores_home=os.path.realpath(chores_home),
        state_dir=os.path.realpath(state),
        data_dir=os.path.realpath(data),
    )


def _pointer(state: Path) -> str | None:
    try:
        return (state / HOME_POINTER).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def remember_home(paths: Paths) -> None:
    """Persist paths.chores_home as the pointer (called by `chores install`)."""
    state = Path(paths.state_dir)
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    (state / HOME_POINTER).write_text(paths.chores_home + "\n", encoding="utf-8")


def forget_home(paths: Paths) -> None:
    (Path(paths.state_dir) / HOME_POINTER).unlink(missing_ok=True)


def _launch_factory(state_dir: Path) -> Callable[[str], None]:
    def launch(name: str) -> None:
        log = state_dir / "spawn.log"
        with log.open("ab") as fh:
            subprocess.Popen(
                [sys.executable, "-m", "chores", "run", name],
                stdin=subprocess.DEVNULL,
                stdout=fh,
                stderr=fh,
                start_new_session=True,
                close_fds=True,
            )

    return launch


def build_deps(*, installed_probe: Callable[[], bool | None] | None = None) -> Deps:
    paths = resolve_paths()
    state_dir = Path(paths.state_dir)
    process = SubprocessRunner()
    installer = installer_for(
        platform.system(),
        home=Path(os.environ.get("HOME", "~")).expanduser(),
        uid=os.getuid(),
    )
    if installed_probe is None:
        installed_probe = (
            (lambda: installer.installed()) if installer else (lambda: None)
        )
    return Deps(
        definitions=DefinitionsLoader(Path(paths.chores_home)),
        catalog_for=lambda defs: _catalog(defs, process),
        store=FsRunStore(state_dir),
        clock=SystemClock(),
        process=process,
        secrets=OpSecrets(),
        power=SystemPower(),
        network=SocketNetwork(),
        notifier=DesktopNotifier(),
        workspaces=FsWorkspaces(Path(paths.data_dir) / "workspaces"),
        paths=paths,
        inherited_env=dict(os.environ),
        run_id_suffix=lambda: secrets.token_hex(2),
        launch=_launch_factory(state_dir),
        scheduler_installed=installed_probe,
        installer=installer,
    )


def _catalog(defs: Definitions, process: SubprocessRunner) -> BackendCatalog:
    return BackendCatalog(defs.backends, process=process)
