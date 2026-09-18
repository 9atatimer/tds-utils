"""claude-cli AgentPort adapter over the fake ProcessPort (Subsystem 4, lesson 19)."""

from __future__ import annotations

import json

import pytest

from chores.adapters.claude_cli import ClaudeCliAgent
from chores.domain.run import Billing
from chores.ports.agent import AgentTask, ProcessIdentity
from chores.ports.errors import BackendError, Unauthorized

from ._fakes import FakeProcess

TASK = AgentTask(
    body="Review it.",
    model="sonnet",
    cwd="/tmp/ws",
    allowed_tools=frozenset({"Read", "Grep"}),
    max_turns=5,
    timeout_sec=120,
    env={"HOME": "/home/t", "PATH": "/usr/bin", "CHORES_RUN_ID": "r1"},
)
RESULT = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "num_turns": 2,
    "result": "Looks fine.",
    "total_cost_usd": 0.0486,
    "usage": {
        "input_tokens": 2,
        "cache_creation_input_tokens": 10979,
        "cache_read_input_tokens": 18531,
        "output_tokens": 4,
    },
}


def test_argv_carries_isolation_flags_tools_and_turn_cap() -> None:
    """Given a task, Then the argv disables MCP and settings sources and caps turns."""
    proc = FakeProcess(exit_code=0, stdout=json.dumps(RESULT))
    started: list[ProcessIdentity] = []
    ClaudeCliAgent(proc, binary="claude").run(TASK, on_start=started.append)
    argv = list(proc.requests[0].argv)
    assert argv[:2] == ["claude", "-p"]
    assert "--strict-mcp-config" in argv
    assert argv[argv.index("--mcp-config") + 1] == '{"mcpServers":{}}'
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert argv[argv.index("--max-turns") + 1] == "5"
    assert argv[argv.index("--model") + 1] == "sonnet"
    assert set(argv[argv.index("--allowedTools") + 1 :][:2]) == {"Read", "Grep"}
    assert (
        "--output-format" in argv and argv[argv.index("--output-format") + 1] == "json"
    )
    assert proc.requests[0].cwd == "/tmp/ws" and proc.requests[0].env == TASK.env
    assert proc.requests[0].stdin_text == "Review it."
    assert started == [ProcessIdentity(pid=777, pgid=777, process_start=2.0)]


def test_result_parses_usage_turns_and_subscription_cost() -> None:
    out = ClaudeCliAgent(FakeProcess(stdout=json.dumps(RESULT))).run(
        TASK, on_start=lambda _: None
    )
    assert out.text == "Looks fine." and out.turns == 2
    assert out.tokens_in == 2 + 10979 + 18531 and out.tokens_out == 4
    assert out.usd == pytest.approx(0.0486) and out.billing is Billing.SUBSCRIPTION
    assert out.exit_code == 0 and out.timed_out is False


def test_timeout_and_nonzero_exit_are_reported_not_raised() -> None:
    out = ClaudeCliAgent(
        FakeProcess(exit_code=137, stdout="", stderr="killed", timed_out=True)
    ).run(TASK, on_start=lambda _: None)
    assert out.timed_out and out.exit_code == 137 and out.text == ""


def test_auth_failure_maps_to_unauthorized_and_garbage_to_backend_error() -> None:
    with pytest.raises(Unauthorized):
        ClaudeCliAgent(
            FakeProcess(exit_code=1, stderr="Not logged in. Please run /login")
        ).run(TASK, on_start=lambda _: None)
    with pytest.raises(BackendError):
        ClaudeCliAgent(FakeProcess(exit_code=0, stdout="not json")).run(
            TASK, on_start=lambda _: None
        )


def test_is_error_result_is_a_backend_error_carrying_the_text() -> None:
    bad = {
        **RESULT,
        "is_error": True,
        "subtype": "error_max_turns",
        "result": "hit max turns",
    }
    with pytest.raises(BackendError) as exc:
        ClaudeCliAgent(FakeProcess(stdout=json.dumps(bad))).run(
            TASK, on_start=lambda _: None
        )
    assert "error_max_turns" in str(exc.value)


def test_claude_response_without_a_result_string_is_a_backend_error() -> None:
    import json

    from chores.adapters.claude_cli import ClaudeCliAgent
    from chores.ports.agent import AgentTask

    process = FakeProcess(stdout=json.dumps({}))
    agent = ClaudeCliAgent(process, binary="claude")
    with pytest.raises(BackendError, match="no result string"):
        agent.run(
            AgentTask(
                body="x",
                model="m",
                cwd="/tmp",
                allowed_tools=frozenset(),
                max_turns=1,
                timeout_sec=1.0,
                env={},
                kill_grace_sec=1,
            ),
            on_start=lambda _identity: None,
        )


def test_the_output_cap_reaches_the_process_and_truncation_is_reported() -> None:
    """The adapter passes the run-dir cap down to the process runner and
    reports back what the runner dropped."""
    from dataclasses import replace

    proc = FakeProcess(stdout=json.dumps(RESULT))
    proc.result = replace(proc.result, output_truncated=True)
    out = ClaudeCliAgent(proc).run(
        AgentTask(
            body="hi",
            model="sonnet",
            cwd="/",
            allowed_tools=frozenset(),
            max_turns=None,
            timeout_sec=5,
            env={},
            max_output_bytes=4096,
        ),
        on_start=lambda _identity: None,
    )
    assert proc.requests[0].max_output_bytes == 4096 and out.output_truncated is True
