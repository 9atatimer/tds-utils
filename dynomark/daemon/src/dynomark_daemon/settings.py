"""The daemon's settings: the domain ``Config`` plus where things live.

Read once by the entry points, never by a use case (DYNOMARK.DESIGN.md, The
daemon, "Config -- loaded once by the composition root"). Sources, first
wins: the environment, ``$XDG_CONFIG_HOME/dynomark/config.toml`` (default
``~/.config/dynomark/config.toml``), then the defaults below. A missing
file is the defaults, with role ``reader``: a fresh install never writes to
the bookmark tree until told to. An unknown key or a bad value is a
``ConfigError`` naming it.

Files: state ``$XDG_STATE_HOME/dynomark`` (default
``~/.local/state/dynomark``) holds the store, the log and the socket;
``$DYNOMARK_SOCKET`` overrides the socket (contract/v1 README, Endpoint).
Models are Ollama model names at ``$OLLAMA_HOST`` (default
``http://127.0.0.1:11434``); their ``Config`` ids are ``ollama:<name>``.
"""

import re
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeVar
from urllib.parse import urlsplit

from dynomark_daemon.domain.config import Config, ModelInfo
from dynomark_daemon.domain.ids import HostId
from dynomark_daemon.domain.job import RetryPolicy
from dynomark_daemon.domain.roles import HostRole
from dynomark_daemon.domain.tree import FolderPath, OwnedRoots, RootKey

T = TypeVar("T")

# --- Constants ---

APP: Final = "dynomark"
SOCKET_NAME: Final = "daemon.sock"
STORE_NAME: Final = "corpus.sqlite3"
LOG_NAME: Final = "daemon.log"
CONFIG_NAME: Final = "config.toml"

DEFAULT_OLLAMA: Final = "http://127.0.0.1:11434"
DEFAULT_EMBEDDING: Final = "nomic-embed-text"
DEFAULT_COMPLETION: Final = "llama3.1:8b"
"""Default local models: design Open Question 4, answered provisionally."""
DEFAULT_MODEL_TIMEOUT_S: Final = 120.0
DEFAULT_RETRY: Final = RetryPolicy(
    attempts=3, initial_backoff_ms=5_000, max_backoff_ms=300_000
)
DEFAULT_FETCH_TIMEOUT_S: Final = 15.0
DEFAULT_FETCH_MAX_BYTES: Final = 5_000_000
DEFAULT_ROOTS: Final = OwnedRoots(
    follow_up=FolderPath(root=RootKey.BAR, names=("Follow Up",)),
    dynomark=FolderPath(root=RootKey.BAR, names=("Dynomark",)),
    graveyard=FolderPath(root=RootKey.BAR, names=("Graveyard",)),
)
LOOPBACK: Final = frozenset({"127.0.0.1", "localhost", "::1"})
HOST_ID: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
NOT_HOST_ID: Final = re.compile(r"[^A-Za-z0-9._-]+")

SCHEMA: Final[Mapping[str, frozenset[str]]] = {
    "": frozenset(
        {"host_id", "role", "models", "store", "socket", "retry", "capture", "diffs"}
    ),
    "models": frozenset({"embedding", "completion", "timeout_s"}),
    "store": frozenset({"path"}),
    "socket": frozenset({"path"}),
    "retry": frozenset({"attempts", "initial_backoff_ms", "max_backoff_ms"}),
    "capture": frozenset({"fetch_timeout_s", "max_bytes"}),
    "diffs": frozenset({"rebuild_every_hours"}),
}
HOUR_MS: Final = 3_600_000


class ConfigError(ValueError):
    """The config file is not TOML, or a key or value is not one we know."""


@dataclass(frozen=True, slots=True)
class CaptureSettings:
    """The fetch adapter's limits."""

    fetch_timeout_s: float
    max_bytes: int


@dataclass(frozen=True, slots=True)
class Settings:
    """``Config`` for the use cases, and what the adapters need."""

    config: Config
    config_path: Path
    config_found: bool
    state_dir: Path
    socket_path: Path
    log_path: Path
    ollama_url: str
    embedding_name: str
    completion_name: str
    model_timeout_s: float
    capture: CaptureSettings


# --- Paths ---


def _xdg(env: Mapping[str, str], name: str, home: Path, fallback: str) -> Path:
    value = env.get(name, "")
    base = Path(value) if value and Path(value).is_absolute() else home / fallback
    return base / APP


def state_dir(env: Mapping[str, str], *, home: Path) -> Path:
    return _xdg(env, "XDG_STATE_HOME", home, ".local/state")


def config_path(env: Mapping[str, str], *, home: Path) -> Path:
    return _xdg(env, "XDG_CONFIG_HOME", home, ".config") / CONFIG_NAME


def socket_path(env: Mapping[str, str], *, home: Path) -> Path:
    value = env.get("DYNOMARK_SOCKET", "")
    return Path(value) if value else state_dir(env, home=home) / SOCKET_NAME


def ollama_url(env: Mapping[str, str]) -> str:
    """``$OLLAMA_HOST`` as a URL (Ollama accepts ``host:port`` there too)."""
    value = env.get("OLLAMA_HOST", "").strip() or DEFAULT_OLLAMA
    return value if "://" in value else f"http://{value}"


def _expand(value: str, home: Path) -> Path:
    if value == "~" or value.startswith("~/"):
        return home / value[2:]
    return Path(value)


# --- Values ---


def _table(document: Mapping[str, object], name: str) -> Mapping[str, object]:
    table = document.get(name, {})
    if not isinstance(table, dict):
        raise ConfigError(f"{name}: expected a table")
    return {str(key): value for key, value in table.items()}


def _check_keys(document: Mapping[str, object]) -> None:
    for table, allowed in SCHEMA.items():
        values = document if table == "" else _table(document, table)
        for key in values:
            if key not in allowed:
                where = f"{table}.{key}" if table else key
                raise ConfigError(f"{where}: unknown key")


def _value(
    table: Mapping[str, object],
    where: str,
    key: str,
    default: T,
    check: Callable[[object], bool],
) -> T:
    value = table.get(key, default)
    if not check(value):
        raise ConfigError(f"{where}: {value!r} is not allowed here")
    return value  # type: ignore[return-value]  # check() proved its type


def _is_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _is_seconds(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and value > 0


def default_host_id(hostname: str) -> HostId:
    """A valid ``HostId`` from the machine name (``.local`` dropped)."""
    name = hostname.removesuffix(".local")
    candidate = NOT_HOST_ID.sub("-", name).strip("-._")[:64]
    return HostId(candidate or "dynomark")


def _host_id(document: Mapping[str, object], hostname: str) -> HostId:
    value = document.get("host_id")
    if value is None:
        return default_host_id(hostname)
    if not isinstance(value, str) or HOST_ID.fullmatch(value) is None:
        raise ConfigError(f"host_id: {value!r} is not a host id")
    return HostId(value)


def _role(document: Mapping[str, object]) -> HostRole:
    value = document.get("role", HostRole.READER.value)
    if not isinstance(value, str) or value not in {r.value for r in HostRole}:
        raise ConfigError(f"role: {value!r} is not writer or reader")
    return HostRole(value)


def _retry(document: Mapping[str, object]) -> RetryPolicy:
    table = _table(document, "retry")
    fields = {
        key: _value(table, f"retry.{key}", key, getattr(DEFAULT_RETRY, key), _is_count)
        for key in ("attempts", "initial_backoff_ms", "max_backoff_ms")
    }
    return RetryPolicy(**fields)


def _capture(document: Mapping[str, object]) -> CaptureSettings:
    table = _table(document, "capture")
    return CaptureSettings(
        fetch_timeout_s=float(
            _value(
                table,
                "capture.fetch_timeout_s",
                "fetch_timeout_s",
                DEFAULT_FETCH_TIMEOUT_S,
                _is_seconds,
            )
        ),
        max_bytes=_value(
            table,
            "capture.max_bytes",
            "max_bytes",
            DEFAULT_FETCH_MAX_BYTES,
            _is_count,
        ),
    )


def _rebuild_cadence_ms(document: Mapping[str, object]) -> int | None:
    """``[diffs] rebuild_every_hours``; absent: rebuilds are manual only
    (design Open Question 2)."""
    table = _table(document, "diffs")
    if "rebuild_every_hours" not in table:
        return None
    hours = _value(
        table, "diffs.rebuild_every_hours", "rebuild_every_hours", 0.0, _is_seconds
    )
    return int(float(hours) * HOUR_MS)


def _path_setting(
    document: Mapping[str, object], table_name: str, default: Path, home: Path
) -> Path:
    table = _table(document, table_name)
    value = _value(table, f"{table_name}.path", "path", str(default), _is_text)
    return _expand(value, home)


# --- Entry points ---


def parse_settings(
    document: Mapping[str, object] | None,
    env: Mapping[str, str],
    *,
    home: Path,
    hostname: str,
    found_at: Path | None = None,
) -> Settings:
    """Settings from a parsed config file (``None``: no file) and the env.

    Raises:
        ConfigError: an unknown key or a value out of place.
    """
    found = document is not None
    document = document or {}
    _check_keys(document)
    state = state_dir(env, home=home)
    models = _table(document, "models")
    embedding = _value(
        models, "models.embedding", "embedding", DEFAULT_EMBEDDING, _is_text
    )
    completion = _value(
        models, "models.completion", "completion", DEFAULT_COMPLETION, _is_text
    )
    timeout = _value(
        models, "models.timeout_s", "timeout_s", DEFAULT_MODEL_TIMEOUT_S, _is_seconds
    )
    url = ollama_url(env)
    local = (urlsplit(url).hostname or "") in LOOPBACK
    socket_value = env.get("DYNOMARK_SOCKET", "")
    return Settings(
        config=Config(
            host_id=_host_id(document, hostname),
            role=_role(document),
            owned_roots=DEFAULT_ROOTS,
            embedding_model=ModelInfo(model_id=f"ollama:{embedding}", local=local),
            completion_model=ModelInfo(model_id=f"ollama:{completion}", local=local),
            store_path=_path_setting(document, "store", state / STORE_NAME, home),
            retry=_retry(document),
            rebuild_cadence_ms=_rebuild_cadence_ms(document),
        ),
        config_path=found_at or config_path(env, home=home),
        config_found=found,
        state_dir=state,
        socket_path=(
            Path(socket_value)
            if socket_value
            else _path_setting(document, "socket", state / SOCKET_NAME, home)
        ),
        log_path=state / LOG_NAME,
        ollama_url=url,
        embedding_name=embedding,
        completion_name=completion,
        model_timeout_s=float(timeout),
        capture=_capture(document),
    )


def load_settings(env: Mapping[str, str], *, home: Path, hostname: str) -> Settings:
    """Settings from the config file, if there is one, and the environment.

    Raises:
        ConfigError: the file is not TOML or holds a bad key or value.
    """
    path = config_path(env, home=home)
    if not path.is_file():
        return parse_settings(None, env, home=home, hostname=hostname)
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path}: {error}") from error
    return parse_settings(document, env, home=home, hostname=hostname, found_at=path)
