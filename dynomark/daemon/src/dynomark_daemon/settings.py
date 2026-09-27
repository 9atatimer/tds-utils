"""Where the daemon's files live (contract/v1/README.md, Endpoint; XDG Base
Directory): read once by the entry points, never by a use case.

- state: ``$XDG_STATE_HOME/dynomark``, default ``~/.local/state/dynomark``
- socket: ``$DYNOMARK_SOCKET``, else ``<state>/daemon.sock``
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Final

APP: Final = "dynomark"
SOCKET_NAME: Final = "daemon.sock"


def _xdg(env: Mapping[str, str], name: str, home: Path, fallback: str) -> Path:
    value = env.get(name, "")
    base = Path(value) if value and Path(value).is_absolute() else home / fallback
    return base / APP


def state_dir(env: Mapping[str, str], *, home: Path) -> Path:
    return _xdg(env, "XDG_STATE_HOME", home, ".local/state")


def socket_path(env: Mapping[str, str], *, home: Path) -> Path:
    value = env.get("DYNOMARK_SOCKET", "")
    return Path(value) if value else state_dir(env, home=home) / SOCKET_NAME


DEFAULT_OLLAMA: Final = "http://127.0.0.1:11434"
DEFAULT_EMBEDDING: Final = "nomic-embed-text"
DEFAULT_COMPLETION: Final = "llama3.1:8b"


def ollama_url(env: Mapping[str, str]) -> str:
    """``$OLLAMA_HOST`` as a URL (Ollama accepts ``host:port`` there too)."""
    value = env.get("OLLAMA_HOST", "").strip() or DEFAULT_OLLAMA
    return value if "://" in value else f"http://{value}"
