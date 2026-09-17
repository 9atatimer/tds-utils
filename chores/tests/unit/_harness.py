"""A full Deps bundle built from fakes, for CLI and status tests."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path

from chores.adapters.definitions import DefinitionsLoader
from chores.application.deps import Deps
from chores.application.paths import Paths

from ._fakes import (
    FakeAgent,
    FakeClock,
    FakeCompletion,
    FakeNetwork,
    FakeNotifier,
    FakePower,
    FakeProcess,
    FakeRunStore,
    FakeSecrets,
    FakeWorkspaces,
)
from .test_runner import SECRET, FakeCatalog, write_home

T0 = datetime(2026, 3, 2, 10, 0, 30)


class FullHarness:
    def __init__(
        self,
        tmp_path: Path,
        *,
        chores: Mapping[str, str],
        config: str = "",
        completion: FakeCompletion | None = None,
        agent: FakeAgent | None = None,
        process: FakeProcess | None = None,
        env: Mapping[str, str] | None = None,
        installed: bool | None = None,
    ) -> None:
        home = tmp_path / "home"
        write_home(home, chores=chores, config=config)
        self.store = FakeRunStore()
        self.clock = FakeClock(T0, utc_offset=timedelta(hours=-7))
        self.process = process or FakeProcess()
        self.secrets = FakeSecrets(
            {"op://v/gw/password": SECRET, "op://v/other/credential": "other-secret"}
        )
        self.power = FakePower()
        self.network = FakeNetwork()
        self.notifier = FakeNotifier()
        self.workspaces = FakeWorkspaces()
        self.catalog = FakeCatalog(completion=completion, agent=agent)
        self.launched: list[str] = []
        self.paths = Paths(str(home), str(tmp_path / "state"), str(tmp_path / "data"))
        self.definitions = DefinitionsLoader(home, revision_reader=lambda _: "rev1")
        self.env = dict(env or {"PATH": "/usr/bin", "HOME": "/home/t", "LANG": "C"})
        self.installed = installed

    def deps(self) -> Deps:
        return Deps(
            definitions=self.definitions,
            catalog_for=lambda d: self.catalog.bind(d),
            store=self.store,
            clock=self.clock,
            process=self.process,
            secrets=self.secrets,
            power=self.power,
            network=self.network,
            notifier=self.notifier,
            workspaces=self.workspaces,
            paths=self.paths,
            inherited_env=self.env,
            run_id_suffix=lambda: "ab12",
            launch=self.launched.append,
            scheduler_installed=lambda: self.installed,
        )
