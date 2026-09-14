"""The backend registry: type -> port + adapter, and the Swap test (Goals)."""

from __future__ import annotations

import pytest

from chores.adapters.claude_cli import ClaudeCliAgent
from chores.adapters.ollama import OllamaCompletion
from chores.adapters.openai_compat import OpenAICompatCompletion
from chores.adapters.registry import BackendCatalog, BackendType, register_type
from chores.domain.budget import Ceiling
from chores.domain.kinds import ExecutionPort
from chores.ports.backends import BackendConfig, Price

from ._fakes import FakeCompletion, FakeProcess

CONFIGS = {
    "local": BackendConfig(name="local", type="ollama", model="llama3.2"),
    "gw": BackendConfig(
        name="gw",
        type="openai-compat",
        model="openai/gpt-4o-mini",
        base_url="https://gw/v1/x/compat",
        auth_header="cf-aig-authorization",
        credential_ref="op://v/i/password",
        prices={"openai/gpt-4o-mini": Price(0.15, 0.6)},
        ceiling=Ceiling(usd=1.0),
    ),
    "claude": BackendConfig(name="claude", type="claude-cli", model="sonnet"),
    "weird": BackendConfig(name="weird", type="no-such-type"),
}


def catalog() -> BackendCatalog:
    return BackendCatalog(CONFIGS, process=FakeProcess())


def test_spec_derives_port_network_pricing_and_read_only_tools() -> None:
    c = catalog()
    local, gw, claude = c.spec("local"), c.spec("gw"), c.spec("claude")
    assert (
        local
        and local.port is ExecutionPort.COMPLETION
        and local.requires_network is False
    )
    assert (
        gw
        and gw.requires_network is True
        and gw.priced is True
        and gw.ceiling == Ceiling(usd=1.0)
    )
    assert (
        claude
        and claude.port is ExecutionPort.AGENT
        and claude.read_only_tools >= {"Read", "Grep", "Glob"}
    )
    assert local.priced is False and c.spec("nope") is None


def test_unknown_type_is_reported_not_crashed() -> None:
    c = catalog()
    assert c.spec("weird") is None
    assert any("no-such-type" in e for e in c.errors)


def test_adapters_are_built_per_type_with_credentials_supplied_at_the_edge() -> None:
    c = catalog()
    assert isinstance(c.completion("local"), OllamaCompletion)
    gw = c.completion("gw", credential="tok")
    assert isinstance(gw, OpenAICompatCompletion)
    assert isinstance(c.agent("claude"), ClaudeCliAgent)
    assert (
        c.credential_ref("gw") == "op://v/i/password"
        and c.credential_ref("local") is None
    )
    assert (
        c.probe_url("gw") == "https://gw/v1/x/compat" and c.probe_url("local") is None
    )
    with pytest.raises(KeyError):
        c.completion("claude")


def test_swap_test_a_fourth_type_is_one_register_call() -> None:
    """Registering a new completion type needs no change outside the registry."""
    register_type(
        BackendType(
            name="fake-llm",
            port=ExecutionPort.COMPLETION,
            requires_network=False,
            read_only_tools=frozenset(),
            build_completion=lambda cfg, credential, deps: FakeCompletion(
                text="swapped"
            ),
            build_agent=None,
        )
    )
    c = BackendCatalog(
        {"f": BackendConfig(name="f", type="fake-llm", model="m")},
        process=FakeProcess(),
    )
    spec = c.spec("f")
    assert spec and spec.port is ExecutionPort.COMPLETION
    assert isinstance(c.completion("f"), FakeCompletion)
