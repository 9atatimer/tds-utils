"""The full port bundle the composition root builds once; use cases take the
subset they need via the ``as_*`` views."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from chores.application.paths import Paths
from chores.application.run import RunDeps
from chores.application.tick import TickDeps
from chores.ports.backends import BackendCatalogPort
from chores.ports.definitions import Definitions, DefinitionsPort
from chores.ports.host import (
    ClockPort,
    NetworkPort,
    NotifierPort,
    PowerPort,
    SecretsPort,
)
from chores.ports.process import ProcessPort
from chores.ports.store import RunStorePort, WorkspacesPort


@dataclass(frozen=True, slots=True)
class Deps:
    definitions: DefinitionsPort
    catalog_for: Callable[[Definitions], BackendCatalogPort]
    store: RunStorePort
    clock: ClockPort
    process: ProcessPort
    secrets: SecretsPort
    power: PowerPort
    network: NetworkPort
    notifier: NotifierPort
    workspaces: WorkspacesPort
    paths: Paths
    inherited_env: Mapping[str, str]
    run_id_suffix: Callable[[], str]
    launch: Callable[[str], None]
    scheduler_installed: Callable[[], bool | None]

    def as_run_deps(self) -> RunDeps:
        return RunDeps(
            definitions=self.definitions,
            catalog_for=self.catalog_for,
            store=self.store,
            clock=self.clock,
            process=self.process,
            secrets=self.secrets,
            power=self.power,
            network=self.network,
            notifier=self.notifier,
            workspaces=self.workspaces,
            paths=self.paths,
            inherited_env=self.inherited_env,
            run_id_suffix=self.run_id_suffix,
        )

    def as_tick_deps(self) -> TickDeps:
        return TickDeps(
            definitions=self.definitions,
            catalog_for=self.catalog_for,
            store=self.store,
            clock=self.clock,
            process=self.process,
            power=self.power,
            network=self.network,
            notifier=self.notifier,
            paths=self.paths,
            launch=self.launch,
            run_id_suffix=self.run_id_suffix,
        )
