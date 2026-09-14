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


def resolve_paths(env: dict[str, str] | None = None) -> Paths:
    e = os.environ if env is None else env
    home = Path(e.get("HOME", "~")).expanduser()
    chores_home = Path(e.get("CHORES_HOME", home / ".config" / "chores")).expanduser()
    state = (
        Path(e.get("XDG_STATE_HOME", home / ".local" / "state")).expanduser() / "chores"
    )
    data = (
        Path(e.get("XDG_DATA_HOME", home / ".local" / "share")).expanduser() / "chores"
    )
    return Paths(chores_home=str(chores_home), state_dir=str(state), data_dir=str(data))


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
