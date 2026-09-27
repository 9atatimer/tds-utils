"""The daemon's Config from TOML (DYNOMARK.DESIGN.md, Ubiquitous language:
"Config -- HostRole, model ids, store path, RetryPolicy"; The daemon,
"Config -- loaded once by the composition root"; contract/v1 README,
Endpoint: the socket path). Parsing is pure: the TOML text is an input.

A missing file gives documented defaults with role reader, so a fresh
install never writes until told.
"""

import tomllib
from pathlib import Path, PurePath

import pytest

from dynomark_daemon.domain.config import ModelInfo
from dynomark_daemon.domain.job import RetryPolicy
from dynomark_daemon.domain.roles import HostRole
from dynomark_daemon.domain.tree import RootKey
from dynomark_daemon.settings import ConfigError, Settings, parse_settings

HOME = Path("/home/ada")
FULL = """
host_id = "mbp"
role = "writer"

[models]
embedding = "mxbai-embed-large"
completion = "qwen2.5:7b"
timeout_s = 90

[store]
path = "~/dynomark/corpus.sqlite3"

[socket]
path = "/run/user/501/dynomark.sock"

[retry]
attempts = 5
initial_backoff_ms = 2000
max_backoff_ms = 600000

[capture]
fetch_timeout_s = 7.5
max_bytes = 1000000
private_addresses = true
"""


def _parse(
    text: str | None, env: dict[str, str] | None = None, hostname: str = "Ada-MBP.local"
) -> Settings:
    document = None if text is None else tomllib.loads(text)
    return parse_settings(document, env or {}, home=HOME, hostname=hostname)


def test_no_config_file_gives_documented_defaults_with_role_reader() -> None:
    """Given no config file, When settings are parsed, Then the host is a reader
    named after the machine, with the default local models, retry policy and
    files under ~/.local/state/dynomark, and the fetch reaches only public
    addresses."""
    settings = _parse(None)
    config = settings.config

    assert config.role is HostRole.READER
    assert config.host_id == "Ada-MBP"
    assert config.embedding_model == ModelInfo("ollama:nomic-embed-text", local=True)
    assert config.completion_model == ModelInfo("ollama:llama3.1:8b", local=True)
    assert config.retry == RetryPolicy(
        attempts=3, initial_backoff_ms=5_000, max_backoff_ms=300_000
    )
    assert config.store_path == PurePath(
        "/home/ada/.local/state/dynomark/corpus.sqlite3"
    )
    assert settings.socket_path == Path("/home/ada/.local/state/dynomark/daemon.sock")
    assert settings.log_path == Path("/home/ada/.local/state/dynomark/daemon.log")
    assert settings.ollama_url == "http://127.0.0.1:11434"
    assert config.owned_roots.dynomark.root is RootKey.BAR
    assert config.owned_roots.dynomark.names == ("Dynomark",)
    assert settings.capture.private_addresses is False
    assert not settings.config_found


def test_a_full_config_file_sets_every_value() -> None:
    """Given every key set, When parsed, Then each lands in Config or the
    adapter settings, and ~ expands to the home directory."""
    settings = _parse(FULL)
    config = settings.config

    assert (config.host_id, config.role) == ("mbp", HostRole.WRITER)
    assert config.embedding_model.model_id == "ollama:mxbai-embed-large"
    assert config.completion_model.model_id == "ollama:qwen2.5:7b"
    assert (settings.embedding_name, settings.completion_name) == (
        "mxbai-embed-large",
        "qwen2.5:7b",
    )
    assert settings.model_timeout_s == 90.0
    assert config.store_path == PurePath("/home/ada/dynomark/corpus.sqlite3")
    assert settings.socket_path == Path("/run/user/501/dynomark.sock")
    assert config.retry == RetryPolicy(
        attempts=5, initial_backoff_ms=2_000, max_backoff_ms=600_000
    )
    assert (settings.capture.fetch_timeout_s, settings.capture.max_bytes) == (
        7.5,
        1_000_000,
    )
    assert settings.capture.private_addresses is True
    assert settings.config_found


def test_the_environment_places_state_socket_and_ollama() -> None:
    """Given XDG_STATE_HOME, DYNOMARK_SOCKET and a remote OLLAMA_HOST, When
    parsed, Then the store follows the state home, the socket the variable
    (over the file), and the models are marked not local."""
    env = {
        "XDG_STATE_HOME": "/var/state",
        "DYNOMARK_SOCKET": "/tmp/d.sock",
        "OLLAMA_HOST": "gpu-box:11434",
    }

    settings = _parse(FULL.replace('path = "~/dynomark/corpus.sqlite3"', ""), env)

    assert settings.config.store_path == PurePath("/var/state/dynomark/corpus.sqlite3")
    assert settings.socket_path == Path("/tmp/d.sock")
    assert settings.ollama_url == "http://gpu-box:11434"
    assert not settings.config.embedding_model.local


@pytest.mark.parametrize(
    ("text", "names"),
    [
        ('rol = "writer"', "rol"),
        ('role = "admin"', "role"),
        ("role = 1", "role"),
        ('host_id = "-bad id"', "host_id"),
        ("[retry]\nattempts = 0", "retry.attempts"),
        ('[retry]\nattempts = "5"', "retry.attempts"),
        ("[retry]\nattempts = true", "retry.attempts"),
        ("[models]\nembedding = ''", "models.embedding"),
        ("[capture]\nmax_bytes = -1", "capture.max_bytes"),
        ('[capture]\nprivate_addresses = "yes"', "capture.private_addresses"),
        ("[store]\nsize = 1", "store.size"),
    ],
)
def test_a_bad_value_or_unknown_key_is_a_config_error_naming_it(
    text: str, names: str
) -> None:
    """Given an unknown key, a wrong type or an out-of-range value, When parsed,
    Then ConfigError names the key (a typo never silently falls back)."""
    with pytest.raises(ConfigError, match=names.replace(".", r"\.")):
        _parse(text)


def test_a_hostname_that_is_no_host_id_is_made_into_one() -> None:
    """Given a machine name with spaces and a leading symbol, When no host_id is
    configured, Then the default is a valid HostId built from it."""
    assert _parse(None, hostname="_Ada's MacBook Pro").config.host_id == (
        "Ada-s-MacBook-Pro"
    )


def test_rebuild_is_manual_unless_a_cadence_is_configured() -> None:
    """Given no [diffs] table, When parsed, Then there is no rebuild cadence
    (design Open Question 2: manual by default); Given rebuild_every_hours,
    Then the cadence is that many hours in milliseconds."""
    assert _parse(None).config.rebuild_cadence_ms is None
    configured = _parse("[diffs]\nrebuild_every_hours = 24")
    assert configured.config.rebuild_cadence_ms == 86_400_000
    with pytest.raises(ConfigError, match=r"diffs\.rebuild_every_hours"):
        _parse("[diffs]\nrebuild_every_hours = 0")
