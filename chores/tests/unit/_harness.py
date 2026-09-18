"""Shared test fixtures: the fake backend catalog, a written $CHORES_HOME,
the definition texts every suite runs against, and the full Deps bundle built
from fakes.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path

from chores.adapters.definitions import DefinitionsLoader
from chores.application.deps import Deps
from chores.application.paths import Paths
from chores.domain.budget import Ceiling
from chores.domain.chore import BackendSpec
from chores.domain.kinds import ExecutionPort
from chores.domain.run import Billing
from chores.ports.definitions import Definitions

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

SECRET = "sk-verysecret/1"
T0 = datetime(2026, 3, 2, 10, 0, 30)


class FakeCatalog:
    def __init__(
        self,
        *,
        completion: FakeCompletion | None = None,
        agent: FakeAgent | None = None,
    ) -> None:
        self._completion = completion or FakeCompletion()
        self._agent = agent or FakeAgent()
        self.credentials: list[str | None] = []
        self.errors: list[str] = []
        self.defs: Definitions | None = None

    def bind(self, defs: Definitions) -> FakeCatalog:
        """What the real catalog gets at construction: the loaded definitions,
        so backends the fixtures do not hard-code still resolve to a spec."""
        self.defs = defs
        return self

    def _from_config(self, name: str) -> BackendSpec | None:
        cfg = self.defs.backends.get(name) if self.defs is not None else None
        if cfg is None:
            return None
        billing = {"ollama": Billing.NONE, "claude-cli": Billing.SUBSCRIPTION}.get(
            cfg.type, Billing.METERED
        )
        return BackendSpec(
            name=name,
            port=ExecutionPort.AGENT
            if cfg.type == "claude-cli"
            else ExecutionPort.COMPLETION,
            default_model=cfg.model,
            requires_network=(
                cfg.requires_network
                if cfg.requires_network is not None
                else cfg.type != "ollama"
            ),
            priced=bool(cfg.prices),
            ceiling=cfg.ceiling,
            read_only_tools=frozenset(),
            priced_models=frozenset(cfg.prices),
            billing=billing,
        )

    def spec(self, name: str) -> BackendSpec | None:
        if name not in ("gw", "local", "claude"):
            return self._from_config(name)
        if name == "gw":
            return BackendSpec(
                "gw",
                ExecutionPort.COMPLETION,
                "m",
                True,
                True,
                Ceiling(usd=1.0),
                frozenset(),
            )
        if name == "local":
            return BackendSpec(
                "local",
                ExecutionPort.COMPLETION,
                "llama",
                False,
                False,
                Ceiling(),
                frozenset(),
            )
        if name == "claude":
            return BackendSpec(
                "claude",
                ExecutionPort.AGENT,
                "sonnet",
                True,
                True,
                Ceiling(),
                frozenset({"Read"}),
            )
        return None

    def credential_ref(self, name: str) -> str | None:
        return "op://v/gw/password" if name == "gw" else None

    def probe_url(self, name: str) -> str | None:
        return "https://gw.example" if name == "gw" else None

    def completion(self, name: str, *, credential: str | None = None) -> FakeCompletion:
        self.credentials.append(credential)
        return self._completion

    def agent(self, name: str, *, credential: str | None = None) -> FakeAgent:
        return self._agent


def write_home(home: Path, *, chores: Mapping[str, str], config: str = "") -> None:
    (home / "chores").mkdir(parents=True, exist_ok=True)
    for name, text in chores.items():
        (home / "chores" / f"{name}.md").write_text(text)
    (home / "backends.yaml").write_text(
        "backends:\n"
        "  gw:\n    type: openai-compat\n    base_url: https://gw.example\n"
        "    model: m\n"
        "    credential_ref: 'op://v/gw/password'\n"
        "    prices: {m: {in_per_1m: 1, out_per_1m: 1}}\n    ceiling: {usd: 1.0}\n"
        "  local: {type: ollama, model: llama}\n"
        "  claude: {type: claude-cli, model: sonnet}\n"
    )
    (home / "config.yaml").write_text(config)


PROMPT = (
    "---\nname: brand\nschedule: '0 3 * * *'\nkind: prompt\nbackend: gw\n"
    "budget: {usd: 0.10, tokens: 4000}\n"
    "secrets: {API_KEY: 'op://v/other/credential'}\n---\nSummarize.\n"
)
LOCAL = (
    "---\nname: loc\nschedule: '0 3 * * *'\nkind: prompt\nbackend: local\n"
    "budget: {tokens: 100}\n---\nHi.\n"
)
COMMAND = (
    "---\nname: tidy\nschedule: '* * * * *'\nkind: command\ncommand: [echo, hi]\n"
    "timeout_sec: 5\n---\n"
)
AGENT = (
    "---\nname: rev\nschedule: '0 9 * * *'\nkind: agent\nbackend: claude\n"
    "budget: {usd: 0.5, turns: 5, tokens: 100000}\nallowed_tools: [Read, Grep]\n"
    "---\nReview.\n"
)


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
