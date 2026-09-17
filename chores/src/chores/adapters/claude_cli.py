"""ClaudeCliAgent -- AgentPort over the Claude Code CLI in headless mode.

Load-bearing isolation (CHORES.DESIGN.md Subsystem 4, template-tools lesson
19): every invocation disables the operator's global MCP servers and every
settings source, caps turns, and passes the definition's tool allowlist.
``HOME`` must be in the task environment because the subscription
credential is keychain-bound; the adapter never reads or writes it.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping

from chores.adapters._fields import float_field, int_field
from chores.domain.run import Billing
from chores.ports.agent import AgentResult, AgentTask, ProcessIdentity
from chores.ports.errors import BackendError, Unauthorized
from chores.ports.process import ProcessPort, ProcessRequest

PROVIDER = "claude-cli"
READ_ONLY_TOOLS: frozenset[str] = frozenset({"Read", "Grep", "Glob", "LS", "WebFetch"})
_EMPTY_MCP = '{"mcpServers":{}}'


class ClaudeCliAgent:
    def __init__(self, process: ProcessPort, *, binary: str = "claude") -> None:
        self._process = process
        self._binary = binary

    def run(
        self, task: AgentTask, *, on_start: Callable[[ProcessIdentity], None]
    ) -> AgentResult:
        argv = [
            self._binary,
            "-p",
            "--output-format",
            "json",
            "--model",
            task.model,
            "--strict-mcp-config",
            "--mcp-config",
            _EMPTY_MCP,
            "--setting-sources",
            "",
        ]
        if task.max_turns is not None:
            argv += ["--max-turns", str(task.max_turns)]
        if task.allowed_tools:
            argv += ["--allowedTools", *sorted(task.allowed_tools)]
        running = self._process.spawn(
            ProcessRequest(
                argv=argv,
                cwd=task.cwd,
                env=task.env,
                timeout_sec=task.timeout_sec,
                kill_grace_sec=task.kill_grace_sec,
                stdin_text=task.body,
            )
        )
        on_start(running.identity)
        result = running.wait()
        if result.timed_out:
            return AgentResult(
                text="",
                events=[],
                tokens_in=0,
                tokens_out=0,
                usd=None,
                turns=None,
                billing=Billing.SUBSCRIPTION,
                exit_code=result.exit_code,
                timed_out=True,
                cpu_seconds=result.cpu_seconds,
            )
        if result.exit_code != 0 and not result.stdout.strip():
            if "login" in result.stderr.lower() or "auth" in result.stderr.lower():
                raise Unauthorized(f"{PROVIDER}: {result.stderr.strip()[:200]}")
            raise BackendError(
                f"{PROVIDER}: exit {result.exit_code}: {result.stderr.strip()[:200]}"
            )
        payload = _parse(result.stdout)
        if payload.get("is_error"):
            subtype = payload.get("subtype", "error")
            raise BackendError(f"{PROVIDER}: {subtype}: {payload.get('result', '')}")
        text = payload.get("result")
        if not isinstance(text, str):
            # `{}` is valid JSON and would otherwise be an empty success
            raise BackendError(f"{PROVIDER}: response carried no result string")
        usage = payload.get("usage")
        tokens_in = tokens_out = 0
        if isinstance(usage, Mapping):
            tokens_in = sum(
                int_field(usage.get(k), provider=PROVIDER, field=k)
                for k in (
                    "input_tokens",
                    "cache_creation_input_tokens",
                    "cache_read_input_tokens",
                )
            )
            tokens_out = int_field(
                usage.get("output_tokens"), provider=PROVIDER, field="output_tokens"
            )
        cost = payload.get("total_cost_usd")
        turns = payload.get("num_turns")
        return AgentResult(
            text=text,
            events=[dict(payload)],
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            usd=float_field(cost, provider=PROVIDER, field="total_cost_usd"),
            turns=(
                int_field(turns, provider=PROVIDER, field="num_turns")
                if turns is not None
                else None
            ),
            billing=Billing.SUBSCRIPTION,
            exit_code=result.exit_code,
            timed_out=False,
            cpu_seconds=result.cpu_seconds,
        )


def _parse(stdout: str) -> Mapping[str, object]:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as e:
        raise BackendError(f"{PROVIDER}: output was not JSON: {stdout[:200]!r}") from e
    if not isinstance(payload, dict):
        raise BackendError(f"{PROVIDER}: output was not a JSON object")
    return payload
