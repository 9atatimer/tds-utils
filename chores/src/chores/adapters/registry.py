"""The backend registry: the one place that knows the vendor set
(CHORES.DESIGN.md Subsystem 4, Goals "Swap test"). Adding a backend type is
one adapter module plus one ``register_type`` call; nothing in domain/ or
application/ changes."""

from __future__ import annotations

import urllib.parse
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from chores.adapters.claude_cli import READ_ONLY_TOOLS, ClaudeCliAgent
from chores.adapters.http import HttpTransport, UrllibTransport
from chores.adapters.ollama import DEFAULT_BASE_URL, OllamaCompletion
from chores.adapters.openai_compat import OpenAICompatCompletion
from chores.domain.chore import BackendSpec
from chores.domain.kinds import ExecutionPort
from chores.domain.run import Billing
from chores.ports.agent import AgentPort
from chores.ports.backends import BackendConfig
from chores.ports.completion import CompletionPort
from chores.ports.process import ProcessPort


@dataclass(frozen=True, slots=True)
class Deps:
    transport: HttpTransport
    process: ProcessPort


CompletionBuilder = Callable[[BackendConfig, str | None, Deps], CompletionPort]
AgentBuilder = Callable[[BackendConfig, str | None, Deps], AgentPort]


@dataclass(frozen=True, slots=True)
class BackendType:
    name: str
    port: ExecutionPort
    requires_network: bool
    read_only_tools: frozenset[str]
    build_completion: CompletionBuilder | None
    build_agent: AgentBuilder | None
    requires_base_url: bool = False
    billing: Billing = Billing.METERED


_TYPES: dict[str, BackendType] = {}


def register_type(backend_type: BackendType) -> None:
    _TYPES[backend_type.name] = backend_type


def _ollama(cfg: BackendConfig, credential: str | None, deps: Deps) -> CompletionPort:
    return OllamaCompletion(deps.transport, base_url=cfg.base_url or DEFAULT_BASE_URL)


def _openai_compat(
    cfg: BackendConfig, credential: str | None, deps: Deps
) -> CompletionPort:
    if cfg.base_url is None:  # unreachable: the catalog refuses such a config
        raise KeyError(f"backend {cfg.name!r}: openai-compat needs base_url")
    return OpenAICompatCompletion(
        deps.transport,
        base_url=cfg.base_url,
        auth_header=cfg.auth_header or "Authorization",
        credential=credential or "",
        prices=cfg.prices,
        provider=cfg.name,
    )


def _claude_cli(cfg: BackendConfig, credential: str | None, deps: Deps) -> AgentPort:
    binary = cfg.extra.get("binary", "claude")
    return ClaudeCliAgent(deps.process, binary=str(binary))


register_type(
    BackendType(
        "ollama",
        ExecutionPort.COMPLETION,
        False,
        frozenset(),
        _ollama,
        None,
        billing=Billing.NONE,
    )
)
register_type(
    BackendType(
        "openai-compat",
        ExecutionPort.COMPLETION,
        True,
        frozenset(),
        _openai_compat,
        None,
        requires_base_url=True,
    )
)
register_type(
    BackendType(
        "claude-cli",
        ExecutionPort.AGENT,
        True,
        READ_ONLY_TOOLS,
        None,
        _claude_cli,
        billing=Billing.SUBSCRIPTION,
    )
)


def _config_error(cfg: BackendConfig) -> str | None:
    """Why this configuration cannot become a backend, or None. Checked once
    at catalog build so `chores validate` refuses it before any run starts."""
    kind = _TYPES.get(cfg.type)
    if kind is None:
        return f"unknown type {cfg.type!r}"
    if kind.requires_base_url and not cfg.base_url:
        return f"{cfg.type} needs base_url"
    if cfg.base_url is not None:
        try:
            parsed = urllib.parse.urlparse(cfg.base_url)
            port = parsed.port  # raises ValueError on a non-numeric port
        except ValueError as e:
            return f"base_url {cfg.base_url!r} is malformed: {e}"
        del port
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return f"base_url {cfg.base_url!r} must be http(s)://host[:port]/..."
    return None


class BackendCatalog:
    """BackendCatalogPort over the registry and the configured backends."""

    def __init__(
        self,
        configs: Mapping[str, BackendConfig],
        *,
        process: ProcessPort,
        transport: HttpTransport | None = None,
    ) -> None:
        self._configs = dict(configs)
        self._deps = Deps(transport=transport or UrllibTransport(), process=process)
        self.errors: list[str] = []
        for name, cfg in configs.items():
            error = _config_error(cfg)
            if error is not None:
                self.errors.append(f"backend {name!r}: {error}")
                del self._configs[name]  # a refused backend is not configured

    def _pair(self, name: str) -> tuple[BackendConfig, BackendType] | None:
        cfg = self._configs.get(name)
        if cfg is None:
            return None
        return cfg, _TYPES[cfg.type]

    def spec(self, name: str) -> BackendSpec | None:
        pair = self._pair(name)
        if pair is None:
            return None
        cfg, kind = pair
        return BackendSpec(
            name=name,
            port=kind.port,
            default_model=cfg.model,
            requires_network=(
                cfg.requires_network
                if cfg.requires_network is not None
                else kind.requires_network
            ),
            priced=bool(cfg.prices),
            ceiling=cfg.ceiling,
            read_only_tools=kind.read_only_tools,
            priced_models=frozenset(cfg.prices),
            billing=kind.billing,
        )

    def credential_ref(self, name: str) -> str | None:
        cfg = self._configs.get(name)
        return cfg.credential_ref if cfg else None

    def probe_url(self, name: str) -> str | None:
        pair = self._pair(name)
        if pair is None:
            return None
        cfg, kind = pair
        needs_network = (
            cfg.requires_network
            if cfg.requires_network is not None
            else kind.requires_network
        )
        return cfg.base_url if needs_network and cfg.base_url else None

    def completion(self, name: str, *, credential: str | None = None) -> CompletionPort:
        pair = self._pair(name)
        if pair is None or pair[1].build_completion is None:
            raise KeyError(f"backend {name!r} is not a completion backend")
        return pair[1].build_completion(pair[0], credential, self._deps)

    def agent(self, name: str, *, credential: str | None = None) -> AgentPort:
        pair = self._pair(name)
        if pair is None or pair[1].build_agent is None:
            raise KeyError(f"backend {name!r} is not an agent backend")
        return pair[1].build_agent(pair[0], credential, self._deps)
