"""Chore definition invariants and cross-object bindings (CHORES.DESIGN.md
Subsystem 1, Data Model)."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from chores.domain.budget import Budget, Ceiling
from chores.domain.chore import (
    BackendSpec,
    Chore,
    ExecutionPort,
    InvalidChore,
    Kind,
    check_bindings,
)
from chores.domain.run import RunStatus

PROMPT: Mapping[str, object] = {
    "name": "nightly-brand",
    "schedule": "0 3 * * *",
    "kind": "prompt",
    "backend": "local",
    "budget": {"tokens": 4000},
}
COMPLETION_BACKEND = BackendSpec(
    name="local",
    port=ExecutionPort.COMPLETION,
    default_model="llama3.2",
    requires_network=False,
    priced=False,
    ceiling=Ceiling(),
    read_only_tools=frozenset(),
)
AGENT_BACKEND = BackendSpec(
    name="claude",
    port=ExecutionPort.AGENT,
    default_model="sonnet",
    requires_network=True,
    priced=True,
    ceiling=Ceiling(usd=2.0, turns=200),
    read_only_tools=frozenset({"Read", "Grep", "Glob"}),
)


# --- construction ------------------------------------------------------------


def test_prompt_chore_takes_defaults() -> None:
    """Given a minimal prompt definition, Then defaults from the Data Model apply."""
    c = Chore.from_mapping(PROMPT, body="Summarize the logs.")
    assert c.kind is Kind.PROMPT
    assert c.enabled is True
    assert c.budget == Budget(tokens=4000, seconds=600)
    assert c.cwd is None
    assert c.defer_on_battery is False
    assert c.catch_up is False
    assert c.notify_on == frozenset(
        {
            RunStatus.FAILED,
            RunStatus.TIMED_OUT,
            RunStatus.BUDGET_EXCEEDED,
            RunStatus.OFFLINE,
            RunStatus.INTERRUPTED,
        }
    )
    assert c.body == "Summarize the logs."


def test_command_chore_carries_argv_and_no_backend() -> None:
    """Given a command definition, Then argv is kept and no backend is required."""
    c = Chore.from_mapping(
        {
            "name": "tidy",
            "schedule": "*/5 * * * *",
            "kind": "command",
            "command": ["rm", "-rf", "tmp"],
            "timeout_sec": 30,
        },
        body="",
    )
    assert c.kind is Kind.COMMAND
    assert c.command == ("rm", "-rf", "tmp")
    assert c.backend is None
    assert c.budget.seconds == 30


@pytest.mark.parametrize(
    ("patch", "word"),
    [
        ({"name": "Bad Name"}, "name"),
        ({"schedule": "nope"}, "schedule"),
        ({"kind": "batch"}, "kind"),
        ({"backend": None}, "backend"),
        ({"timeout_sec": 0}, "timeout_sec"),
        ({"budget": {"tokens": -5}}, "budget"),
        ({"budget": {"gallons": 5}}, "budget"),
        ({"notify_on": ["EXPLODED"]}, "notify_on"),
        ({"surprise": 1}, "surprise"),
        ({"allowed_tools": ["Bash"]}, "allowed_tools"),
    ],
)
def test_invalid_definitions_name_the_field(
    patch: Mapping[str, object], word: str
) -> None:
    """Given one bad field, Then InvalidChore names it."""
    data = {**PROMPT, **patch}
    with pytest.raises(InvalidChore) as exc:
        Chore.from_mapping(data, body="x")
    assert word in str(exc.value)


def test_command_kind_requires_command_and_rejects_backend() -> None:
    """Given kind command without argv, or with a backend, Then InvalidChore."""
    with pytest.raises(InvalidChore):
        Chore.from_mapping(
            {"name": "t", "schedule": "* * * * *", "kind": "command"}, body=""
        )
    with pytest.raises(InvalidChore):
        Chore.from_mapping(
            {
                "name": "t",
                "schedule": "* * * * *",
                "kind": "command",
                "command": ["ls"],
                "backend": "local",
            },
            body="",
        )


# --- bindings ----------------------------------------------------------------


def test_bindings_pass_for_matching_port_and_declared_ceiling_dims() -> None:
    """Given an agent chore declaring usd and turns on a backend with those ceilings,
    Then no violations."""
    c = Chore.from_mapping(
        {
            "name": "review",
            "schedule": "0 9 * * *",
            "kind": "agent",
            "backend": "claude",
            "budget": {"usd": 0.5, "turns": 20, "tokens": 50000},
        },
        body="Review the repo.",
    )
    assert (
        check_bindings(
            c, backend=AGENT_BACKEND, global_ceiling=Ceiling(), forbidden_paths=()
        )
        == []
    )


def test_kind_must_match_backend_port() -> None:
    """Given a prompt chore on an agent backend, Then a violation names the port."""
    c = Chore.from_mapping(
        {**PROMPT, "backend": "claude", "budget": {"usd": 1, "turns": 1, "tokens": 1}},
        body="x",
    )
    out = check_bindings(
        c, backend=AGENT_BACKEND, global_ceiling=Ceiling(), forbidden_paths=()
    )
    assert any("port" in v for v in out)


def test_ceiling_dimension_without_declared_budget_is_a_violation() -> None:
    """Given a backend USD ceiling and a chore with no usd budget, Then a violation."""
    c = Chore.from_mapping(
        {
            "name": "review",
            "schedule": "0 9 * * *",
            "kind": "agent",
            "backend": "claude",
            "budget": {"turns": 20},
        },
        body="x",
    )
    out = check_bindings(
        c, backend=AGENT_BACKEND, global_ceiling=Ceiling(), forbidden_paths=()
    )
    assert any("usd" in v for v in out)


def test_global_ceiling_also_requires_declaration() -> None:
    """Given a global token ceiling and no token budget, Then a violation."""
    c = Chore.from_mapping({**PROMPT, "budget": {}}, body="x")
    out = check_bindings(
        c,
        backend=COMPLETION_BACKEND,
        global_ceiling=Ceiling(tokens=1_000_000),
        forbidden_paths=(),
    )
    assert any("tokens" in v for v in out)


def test_usd_ceiling_on_unpriced_backend_is_a_violation() -> None:
    """Given a backend with a USD ceiling but no price table, Then a violation."""
    unpriced = BackendSpec(
        name="gw",
        port=ExecutionPort.COMPLETION,
        default_model="m",
        requires_network=True,
        priced=False,
        ceiling=Ceiling(usd=1.0),
        read_only_tools=frozenset(),
    )
    c = Chore.from_mapping(
        {**PROMPT, "backend": "gw", "budget": {"usd": 0.1, "tokens": 1}}, body="x"
    )
    out = check_bindings(
        c, backend=unpriced, global_ceiling=Ceiling(), forbidden_paths=()
    )
    assert any("price" in v for v in out)


def test_cwd_may_not_be_inside_or_contain_forbidden_paths() -> None:
    """Given cwd under $CHORES_HOME or above the state dir, Then violations."""
    inside = Chore.from_mapping({**PROMPT, "cwd": "/home/t/.config/chores/x"}, body="x")
    above = Chore.from_mapping({**PROMPT, "cwd": "/home/t"}, body="x")
    forbidden = ("/home/t/.config/chores", "/home/t/.local/state/chores")
    assert check_bindings(
        inside,
        backend=COMPLETION_BACKEND,
        global_ceiling=Ceiling(),
        forbidden_paths=forbidden,
    )
    assert check_bindings(
        above,
        backend=COMPLETION_BACKEND,
        global_ceiling=Ceiling(),
        forbidden_paths=forbidden,
    )
    ok = Chore.from_mapping({**PROMPT, "cwd": "/home/t/workplace/x"}, body="x")
    assert (
        check_bindings(
            ok,
            backend=COMPLETION_BACKEND,
            global_ceiling=Ceiling(),
            forbidden_paths=forbidden,
        )
        == []
    )


def test_agent_allowed_tools_default_to_the_backend_read_only_set() -> None:
    """Given an agent chore with no allowed_tools, Then the effective tools are the
    backend's read-only set."""
    c = Chore.from_mapping(
        {
            "name": "review",
            "schedule": "0 9 * * *",
            "kind": "agent",
            "backend": "claude",
            "budget": {"usd": 0.5, "turns": 20, "tokens": 1},
        },
        body="x",
    )
    assert c.effective_tools(AGENT_BACKEND) == frozenset({"Read", "Grep", "Glob"})


def test_turns_ceiling_applies_to_agent_chores_only() -> None:
    """Given a global turns ceiling, Then a prompt chore needs no turns budget but an
    agent chore does."""
    prompt = Chore.from_mapping(PROMPT, body="x")
    assert (
        check_bindings(
            prompt,
            backend=COMPLETION_BACKEND,
            global_ceiling=Ceiling(turns=100),
            forbidden_paths=(),
        )
        == []
    )
    agent = Chore.from_mapping(
        {
            "name": "review",
            "schedule": "0 9 * * *",
            "kind": "agent",
            "backend": "claude",
            "budget": {"usd": 0.5, "tokens": 1},
        },
        body="x",
    )
    out = check_bindings(
        agent, backend=AGENT_BACKEND, global_ceiling=Ceiling(), forbidden_paths=()
    )
    assert any("turns" in v for v in out)


def test_agent_needs_turns_and_a_model_must_exist() -> None:
    backend = BackendSpec(
        "claude", ExecutionPort.AGENT, None, True, True, Ceiling(), frozenset()
    )
    agent = Chore.from_mapping(
        {
            "name": "rev",
            "schedule": "0 9 * * *",
            "kind": "agent",
            "backend": "claude",
            "budget": {"tokens": 1},
        },
        body="x",
    )
    out = check_bindings(
        agent, backend=backend, global_ceiling=Ceiling(), forbidden_paths=()
    )
    assert any("turns" in v for v in out) and any("no model" in v for v in out)


def test_usd_limits_need_the_resolved_model_to_be_priced() -> None:
    from chores.domain.budget import Budget

    gw = BackendSpec(
        name="gw",
        port=ExecutionPort.COMPLETION,
        default_model="m",
        requires_network=True,
        priced=True,
        ceiling=Ceiling(),
        read_only_tools=frozenset(),
        priced_models=frozenset({"m"}),
    )
    base = Chore.from_mapping(
        {
            "name": "p",
            "kind": "prompt",
            "schedule": "* * * * *",
            "backend": "gw",
            "timeout_sec": 5,
            "model": "other",
        },
        body="x",
    )
    assert not check_bindings(
        base, backend=gw, global_ceiling=Ceiling(), forbidden_paths=()
    )
    errors = check_bindings(
        base, backend=gw, global_ceiling=Ceiling(usd=1.0), forbidden_paths=()
    )
    assert any("'other' has no price" in e for e in errors)
    with_budget = Chore.from_mapping(
        {
            "name": "p",
            "kind": "prompt",
            "schedule": "* * * * *",
            "backend": "gw",
            "timeout_sec": 5,
            "model": "other",
            "budget": {"usd": 0.5},
        },
        body="x",
    )
    assert isinstance(with_budget.budget, Budget)
    errors = check_bindings(
        with_budget, backend=gw, global_ceiling=Ceiling(), forbidden_paths=()
    )
    assert any("'other' has no price" in e for e in errors)
    priced = Chore.from_mapping(
        {
            "name": "p",
            "kind": "prompt",
            "schedule": "* * * * *",
            "backend": "gw",
            "timeout_sec": 5,
            "budget": {"usd": 0.5},
        },
        body="x",
    )
    assert not check_bindings(
        priced, backend=gw, global_ceiling=Ceiling(), forbidden_paths=()
    )


def test_a_metered_backend_without_prices_cannot_carry_any_usd_limit() -> None:
    from chores.domain.run import Billing

    def spec(billing: Billing) -> BackendSpec:
        return BackendSpec(
            name="b",
            port=ExecutionPort.COMPLETION,
            default_model="m",
            requires_network=True,
            priced=False,
            ceiling=Ceiling(),
            read_only_tools=frozenset(),
            billing=billing,
        )

    chore = Chore.from_mapping(
        {
            "name": "p",
            "kind": "prompt",
            "schedule": "* * * * *",
            "backend": "b",
            "timeout_sec": 5,
            "budget": {"usd": 0.5},
        },
        body="x",
    )
    metered = check_bindings(
        chore,
        backend=spec(Billing.METERED),
        global_ceiling=Ceiling(),
        forbidden_paths=(),
    )
    assert any("metered but has no price table" in e for e in metered)
    free = check_bindings(
        chore, backend=spec(Billing.NONE), global_ceiling=Ceiling(), forbidden_paths=()
    )
    assert free == []
    plain = Chore.from_mapping(
        {
            "name": "p",
            "kind": "prompt",
            "schedule": "* * * * *",
            "backend": "b",
            "timeout_sec": 5,
        },
        body="x",
    )
    global_cap = check_bindings(
        plain,
        backend=spec(Billing.METERED),
        global_ceiling=Ceiling(usd=2.0),
        forbidden_paths=(),
    )
    assert any("metered but has no price table" in e for e in global_cap)


def test_is_under_treats_the_filesystem_root_as_containing_everything() -> None:
    from chores.domain.chore import is_under

    assert is_under("/home/x", "/") and is_under("/", "/")
    assert not is_under("/", "/home")
    assert is_under("/home/x/y", "/home/x/") and not is_under("/home/xy", "/home/x")


def test_notify_on_members_must_be_status_names() -> None:
    from chores.domain.chore import InvalidChore

    for bad in ([{}], [None], [["SUCCEEDED"]], [3]):
        with pytest.raises(InvalidChore, match="notify_on"):
            Chore.from_mapping({**PROMPT, "notify_on": bad}, body="x")


def test_free_and_subscription_backends_may_carry_a_usd_ceiling_unpriced() -> None:
    from chores.domain.run import Billing

    def spec(billing: Billing) -> BackendSpec:
        return BackendSpec(
            name="b",
            port=ExecutionPort.COMPLETION,
            default_model="m",
            requires_network=False,
            priced=False,
            ceiling=Ceiling(usd=1.0),
            read_only_tools=frozenset(),
            billing=billing,
        )

    chore = Chore.from_mapping(
        {
            "name": "p",
            "kind": "prompt",
            "schedule": "* * * * *",
            "backend": "b",
            "timeout_sec": 5,
            "budget": {"usd": 0.5},
        },
        body="x",
    )
    for free in (Billing.NONE, Billing.SUBSCRIPTION):
        assert not check_bindings(
            chore, backend=spec(free), global_ceiling=Ceiling(), forbidden_paths=()
        )
    assert check_bindings(
        chore,
        backend=spec(Billing.METERED),
        global_ceiling=Ceiling(),
        forbidden_paths=(),
    )
