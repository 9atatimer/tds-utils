"""The run use case (CHORES.DESIGN.md Subsystem 3) against fakes."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from chores.adapters.definitions import DefinitionsLoader
from chores.application.paths import Paths
from chores.application.run import RunDeps, run_chore
from chores.domain.budget import Ceiling
from chores.domain.chore import BackendSpec
from chores.domain.kinds import ExecutionPort
from chores.domain.run import Billing, RunStatus
from chores.ports.definitions import Definitions
from chores.ports.errors import BackendTimeout, Unreachable

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

T0 = datetime(2026, 3, 2, 10, 0)
SECRET = "sk-verysecret/1"


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


class Harness:
    def __init__(
        self,
        tmp_path: Path,
        *,
        chores: Mapping[str, str],
        config: str = "",
        **fakes: object,
    ) -> None:
        home = tmp_path / "home"
        write_home(home, chores=chores, config=config)
        self.store = FakeRunStore()
        self.clock = FakeClock(T0)
        self.process = FakeProcess(**fakes.get("process", {}))  # type: ignore[arg-type]
        self.secrets = FakeSecrets(
            {"op://v/gw/password": SECRET, "op://v/other/credential": "other-secret"}
        )
        self.power = FakePower()
        self.network = FakeNetwork()
        self.notifier = FakeNotifier()
        self.workspaces = FakeWorkspaces()
        self.catalog = FakeCatalog(
            completion=fakes.get("completion"), agent=fakes.get("agent")
        )  # type: ignore[arg-type]
        self.paths = Paths(
            chores_home=str(home),
            state_dir=str(tmp_path / "state"),
            data_dir=str(tmp_path / "data"),
        )
        self.definitions = DefinitionsLoader(home, revision_reader=lambda _: "rev1")

    def deps(self) -> RunDeps:
        return RunDeps(
            definitions=self.definitions,
            catalog_for=lambda d: self.catalog,
            store=self.store,
            clock=self.clock,
            process=self.process,
            secrets=self.secrets,
            power=self.power,
            network=self.network,
            notifier=self.notifier,
            workspaces=self.workspaces,
            paths=self.paths,
            inherited_env={
                "PATH": "/usr/bin",
                "HOME": "/home/t",
                "LANG": "C",
                "JUNK": "no",
            },
            run_id_suffix=lambda: "ab12",
        )


def test_prompt_run_succeeds_with_full_record(tmp_path: Path) -> None:
    """Given a prompt chore, When run, Then SUCCEEDED with usage, transcript, ledger."""
    h = Harness(tmp_path, chores={"brand": PROMPT})
    out = run_chore("brand", h.deps())
    r = out.record
    assert r is not None and r.status is RunStatus.SUCCEEDED
    assert r.run_id == "brand-20260302T100000Z-ab12" and r.definition_rev == "rev1"
    assert r.backend == "gw" and r.model == "m" and r.usage and r.usage.tokens == 15
    assert h.store.read_record(r.run_id) == r
    assert (
        h.store.ledger_count() == 1
        and h.store.ledger_rows()[0]["status"] == "SUCCEEDED"
    )
    transcript = [
        json.loads(line)
        for line in h.store.read_artifact(r.run_id, "transcript.jsonl").splitlines()
    ]
    assert (
        transcript[0]["role"] == "user" and transcript[0]["content"] == "Summarize.\n"
    )
    assert transcript[1]["role"] == "assistant" and transcript[1]["content"] == "ok"
    assert h.store.read_artifact(r.run_id, "definition.md").startswith(
        "---\nname: brand"
    )
    assert h.catalog.credentials == [SECRET]
    assert h.store.notifications() == []


def test_secret_values_never_reach_the_store(tmp_path: Path) -> None:
    """Given a backend that echoes the credential, Then every artifact is redacted."""
    h = Harness(
        tmp_path,
        chores={"brand": PROMPT},
        completion=FakeCompletion(text=f"key={SECRET} json={json.dumps(SECRET)[1:-1]}"),
    )
    out = run_chore("brand", h.deps())
    assert out.record and out.record.status is RunStatus.SUCCEEDED
    for name in h.store.artifacts(out.record.run_id):
        assert SECRET not in h.store.read_artifact(out.record.run_id, name)
        assert "other-secret" not in h.store.read_artifact(out.record.run_id, name)
    assert "[REDACTED]" in h.store.read_artifact(out.record.run_id, "transcript.jsonl")


def test_command_run_builds_explicit_env_and_captures_streams(tmp_path: Path) -> None:
    h = Harness(
        tmp_path,
        chores={"tidy": COMMAND},
        process={"stdout": "hi\n", "stderr": "warn\n"},
    )
    out = run_chore("tidy", h.deps())
    r = out.record
    assert r and r.status is RunStatus.SUCCEEDED and r.exit_code == 0 and r.pid is None
    req = h.process.requests[0]
    assert list(req.argv) == ["echo", "hi"] and req.cwd == "/data/workspaces/tidy"
    assert (
        "JUNK" not in req.env
        and req.env["PATH"] == "/usr/bin"
        and req.env["HOME"] == "/home/t"
    )
    assert req.env["CHORES_RUN_ID"] == r.run_id and req.env["CHORES_CHORE"] == "tidy"
    assert (
        req.env["CHORES_BUDGET_SECONDS"] == "5"
        and "CHORES_BUDGET_TOKENS" not in req.env
    )
    assert h.store.read_artifact(r.run_id, "stdout.log") == "hi\n"
    assert h.store.read_artifact(r.run_id, "stderr.log") == "warn\n"


def test_agent_run_passes_tools_turns_and_secret_names(tmp_path: Path) -> None:
    h = Harness(tmp_path, chores={"rev": AGENT})
    out = run_chore("rev", h.deps())
    assert out.record and out.record.status is RunStatus.SUCCEEDED
    task = h.catalog._agent.tasks[0]
    assert task.allowed_tools == frozenset({"Read", "Grep"}) and task.max_turns == 5
    assert (
        task.env["CHORES_BUDGET_TURNS"] == "5" and task.env["CHORES_SECRET_NAMES"] == ""
    )
    assert out.record.usage and out.record.usage.turns == 3


@pytest.mark.parametrize(
    ("fake", "status", "word"),
    [
        (
            {"completion": FakeCompletion(tokens_in=5000, tokens_out=1)},
            RunStatus.BUDGET_EXCEEDED,
            "tokens",
        ),
        (
            {"completion": FakeCompletion(error=Unreachable("down"))},
            RunStatus.OFFLINE,
            "down",
        ),
        (
            {"completion": FakeCompletion(error=BackendTimeout("slow"))},
            RunStatus.TIMED_OUT,
            "slow",
        ),
    ],
)
def test_prompt_failures_map_to_statuses(
    tmp_path: Path, fake: Mapping[str, object], status: RunStatus, word: str
) -> None:
    h = Harness(tmp_path, chores={"brand": PROMPT}, **fake)
    out = run_chore("brand", h.deps())
    assert (
        out.record and out.record.status is status and word in (out.record.reason or "")
    )
    assert h.store.ledger_rows()[0]["status"] == status.value
    assert [n.level for n in h.store.notifications()] == [
        "alert" if status is RunStatus.BUDGET_EXCEEDED else "info"
    ]


def test_unreachable_local_backend_is_failed_not_offline(tmp_path: Path) -> None:
    h = Harness(
        tmp_path,
        chores={"loc": LOCAL},
        completion=FakeCompletion(error=Unreachable("no ollama")),
    )
    out = run_chore("loc", h.deps())
    assert out.record and out.record.status is RunStatus.FAILED


def test_command_timeout_and_nonzero_exit(tmp_path: Path) -> None:
    h = Harness(
        tmp_path, chores={"tidy": COMMAND}, process={"timed_out": True, "exit_code": -9}
    )
    assert (run_chore("tidy", h.deps()).record or None).status is RunStatus.TIMED_OUT  # type: ignore[union-attr]
    h2 = Harness(
        tmp_path / "b",
        chores={"tidy": COMMAND},
        process={"exit_code": 2, "stderr": "bad"},
    )
    r = run_chore("tidy", h2.deps()).record
    assert r and r.status is RunStatus.FAILED and "exit 2" in (r.reason or "")


def test_kill_marker_records_killed(tmp_path: Path) -> None:
    h = Harness(tmp_path, chores={"tidy": COMMAND}, process={"exit_code": -15})
    h.store.request_kill("tidy-20260302T100000Z-ab12")
    r = run_chore("tidy", h.deps()).record
    assert r and r.status is RunStatus.KILLED


def test_secret_unavailable_fails_naming_the_reference_not_the_value(
    tmp_path: Path,
) -> None:
    h = Harness(tmp_path, chores={"brand": PROMPT})
    h.secrets.values.pop("op://v/other/credential")
    r = run_chore("brand", h.deps()).record
    assert (
        r
        and r.status is RunStatus.FAILED
        and "op://v/other/credential" in (r.reason or "")
    )
    assert h.catalog.credentials == []


def test_paused_skips_even_with_force_and_writes_a_record(tmp_path: Path) -> None:
    h = Harness(tmp_path, chores={"brand": PROMPT})
    h.store.pause("flight")
    out = run_chore("brand", h.deps(), force=True)
    assert (
        out.record
        and out.record.status is RunStatus.SKIPPED_PAUSED
        and "flight" in (out.record.reason or "")
    )
    assert h.catalog.credentials == [] and h.store.ledger_count() == 1


def test_offline_probe_skips_network_chore_and_force_lifts_it(tmp_path: Path) -> None:
    h = Harness(tmp_path, chores={"brand": PROMPT})
    h.network.online = False
    assert (
        run_chore("brand", h.deps()).record or None
    ).status is RunStatus.SKIPPED_OFFLINE  # type: ignore[union-attr]
    assert h.network.probed == ["https://gw.example"]
    assert (
        run_chore("brand", h.deps(), force=True).record or None
    ).status is RunStatus.SUCCEEDED  # type: ignore[union-attr]


def test_ceiling_refusal_writes_skipped_ceiling(tmp_path: Path) -> None:
    h = Harness(tmp_path, chores={"brand": PROMPT})
    for _ in range(10):
        h.clock.advance(60)
        run_chore("brand", h.deps())  # 0.001 usd each; tokens 15 each
    h.store.append_ledger(
        {
            **h.store.ledger_rows()[0],
            "run_id": "x",
            "usd": 0.95,
            "started": T0.isoformat(),
        }
    )
    r = run_chore("brand", h.deps()).record
    assert (
        r
        and r.status is RunStatus.SKIPPED_CEILING
        and "backend usd" in (r.reason or "")
    )


def test_breaker_pauses_chore_after_threshold_and_alerts(tmp_path: Path) -> None:
    h = Harness(
        tmp_path,
        chores={"tidy": COMMAND},
        config="failure_threshold: 2\n",
        process={"exit_code": 1},
    )
    run_chore("tidy", h.deps())
    h.clock.advance(60)
    assert h.store.chore_paused("tidy") is None
    run_chore("tidy", h.deps())
    h.clock.advance(60)
    assert h.store.chore_paused("tidy") is not None
    assert any(
        n.level == "alert" and "paused" in n.text for n in h.store.notifications()
    )
    assert any("paused" in text for _, text in h.notifier.alerts)
    r = run_chore("tidy", h.deps()).record
    assert r and r.status is RunStatus.SKIPPED_PAUSED


def test_dry_run_plans_without_records_or_secrets(tmp_path: Path) -> None:
    h = Harness(tmp_path, chores={"brand": PROMPT})
    out = run_chore("brand", h.deps(), dry_run=True)
    assert out.record is None and out.plan is not None
    assert (
        out.plan.backend == "gw"
        and out.plan.model == "m"
        and "API_KEY" in out.plan.secret_names
    )
    assert SECRET not in str(out.plan) and h.secrets.resolved == []
    assert h.store.records() == [] and out.plan.admission == "ADMIT"


def test_invalid_or_unknown_chore_is_reported(tmp_path: Path) -> None:
    h = Harness(tmp_path, chores={"bad": "---\nname: bad\nkind: prompt\n---\n"})
    out = run_chore("bad", h.deps())
    assert (
        out.record
        and out.record.status is RunStatus.INVALID
        and "schedule" in (out.record.reason or "")
    )
    assert run_chore("nope", h.deps()).record is None


def test_overlap_skips_when_a_live_run_exists(tmp_path: Path) -> None:
    h = Harness(tmp_path, chores={"brand": PROMPT})
    first = run_chore("brand", h.deps()).record
    assert first
    running = first.__class__.pending(
        run_id="brand-x", chore="brand", kind=first.kind, definition_rev="r", started=T0
    ).start(pid=555, pgid=555, process_start=1.0)
    h.store.write_record(running)
    h.process.alive_pids.add(555)
    h.clock.advance(60)
    r = run_chore("brand", h.deps()).record
    assert r and r.status is RunStatus.SKIPPED_OVERLAP and "brand-x" in (r.reason or "")
    assert r.started == T0 + timedelta(seconds=60)
