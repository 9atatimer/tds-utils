"""``dynomark-daemon``: the daemon's command line (Click).

- ``serve``: the socket server and the job loop, until SIGTERM or SIGINT.
- ``check``: config, store health, socket, Ollama and its models. Reads
  only: it creates no file, binds nothing, never touches the tree.
- ``install-host-manifest``: the ``tds.dynomark`` native-messaging manifest
  for Chrome and Chromium, bound to one extension id.
- ``launchd-plist``: a user LaunchAgent plist that runs ``serve``.

Entry points stay thin: parse, call the composition root or an adapter,
print.
"""

import os
import platform
import plistlib
import shutil
import socket
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import click

from dynomark_daemon.adapters.host_manifest import (
    BROWSERS,
    InvalidExtensionId,
    install_manifests,
)
from dynomark_daemon.adapters.ollama import OllamaClient, OllamaError, has_model
from dynomark_daemon.adapters.socket_server import SocketUnavailable
from dynomark_daemon.adapters.sqlite_store import SqliteCorpusStore, StoreError
from dynomark_daemon.container import build_ports, private_state_dir
from dynomark_daemon.container import serve as serve_daemon
from dynomark_daemon.settings import (
    ConfigError,
    Settings,
    config_path,
    host_socket_path,
    load_settings,
)

# --- Constants ---

LABEL: Final = "tds.dynomark.daemon"
PASSED_ENV: Final = (
    "XDG_STATE_HOME",
    "XDG_CONFIG_HOME",
    "DYNOMARK_SOCKET",
    "OLLAMA_HOST",
)
CHECK_TIMEOUT_S: Final = 5.0
OK: Final = "ok"
WARN: Final = "warn"
FAIL: Final = "FAIL"


@dataclass(frozen=True, slots=True)
class CheckLine:
    name: str
    status: str
    detail: str

    def render(self) -> str:
        return f"{self.name:<8}{self.status:<6}{self.detail}"


# --- Helpers ---


def _settings(env: Mapping[str, str]) -> Settings:
    try:
        return load_settings(env, home=Path.home(), hostname=platform.node())
    except ConfigError as error:
        raise click.UsageError(f"config: {error}") from error


def _installed(name: str) -> Path:
    """The console script ``name`` beside this interpreter, else on PATH."""
    beside = Path(sys.executable).parent / name
    if beside.is_file():
        return beside
    found = shutil.which(name)
    return Path(found) if found else Path(sys.argv[0]).resolve().parent / name


def _check_config(settings: Settings) -> list[CheckLine]:
    config = settings.config
    where = (
        str(settings.config_path)
        if settings.config_found
        else f"defaults (no {settings.config_path})"
    )
    return [
        CheckLine("config", OK, where),
        CheckLine(
            "role",
            OK,
            f"{config.role.value}, host {config.host_id}",
        ),
    ]


def _check_store(settings: Settings) -> CheckLine:
    path = Path(settings.config.store_path)
    if not path.exists():
        return CheckLine("store", OK, f"absent: {path} (serve creates it)")
    try:
        store = SqliteCorpusStore.open(path, read_only=True)
    except StoreError as error:
        return CheckLine("store", FAIL, str(error))
    try:
        health = store.health()
    finally:
        store.close()
    status = OK if health.integrity == "ok" else FAIL
    return CheckLine(
        "store",
        status,
        f"{path}: schema {health.schema_version}, {health.entries} entries, "
        f"{health.jobs} jobs, integrity {health.integrity}",
    )


def _check_socket(path: Path) -> CheckLine:
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    probe.settimeout(CHECK_TIMEOUT_S)
    try:
        probe.connect(str(path))
    except OSError:
        return CheckLine("socket", WARN, f"not listening: {path} (daemon down)")
    finally:
        probe.close()
    return CheckLine("socket", OK, f"listening: {path}")


def _check_ollama(settings: Settings) -> list[CheckLine]:
    client = OllamaClient(settings.ollama_url, timeout_s=CHECK_TIMEOUT_S)
    try:
        installed = client.installed_models()
    except OllamaError as error:
        return [
            CheckLine("ollama", FAIL, f"{settings.ollama_url} unreachable: {error}"),
            CheckLine("models", FAIL, "unknown (Ollama unreachable)"),
        ]
    wanted = (settings.embedding_name, settings.completion_name)
    missing = [name for name in wanted if not has_model(installed, name)]
    reach = CheckLine("ollama", OK, f"{settings.ollama_url} reachable")
    if missing:
        return [reach, CheckLine("models", FAIL, f"not pulled: {', '.join(missing)}")]
    return [reach, CheckLine("models", OK, ", ".join(wanted))]


def run_check(settings: Settings) -> list[CheckLine]:
    return [
        *_check_config(settings),
        _check_store(settings),
        _check_socket(settings.socket_path),
        *_check_ollama(settings),
    ]


def passed_env(env: Mapping[str, str]) -> dict[str, str]:
    """What the LaunchAgent hands the daemon from the installing shell."""
    return {k: env[k] for k in PASSED_ENV if env.get(k)}


def launchd_plist(program: Path, settings: Settings, env: Mapping[str, str]) -> bytes:
    """A user LaunchAgent running ``<program> serve`` at load, kept alive."""
    document: dict[str, object] = {
        "Label": LABEL,
        "ProgramArguments": [str(program), "serve"],
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(settings.state_dir / "launchd.out.log"),
        "StandardErrorPath": str(settings.state_dir / "launchd.err.log"),
        "EnvironmentVariables": passed_env(env),
    }
    return plistlib.dumps(document)


# --- Entry points ---


@click.group()
def main() -> None:
    """Dynomark daemon: live AI filing for native browser bookmarks."""


@main.command()
def serve() -> None:
    """Run the socket server and the job loop until SIGTERM or SIGINT."""
    settings = _settings(os.environ)
    private_state_dir(settings)
    try:
        serve_daemon(settings, build_ports(settings))
    except SocketUnavailable as error:
        raise click.ClickException(str(error)) from error


@main.command()
def check() -> None:
    """Report config, store, socket, Ollama and models; change nothing."""
    lines = run_check(_settings(os.environ))
    for line in lines:
        click.echo(line.render())
    if any(line.status == FAIL for line in lines):
        sys.exit(1)


@main.command("install-host-manifest")
@click.option("--extension-id", required=True, help="The unpacked extension's id.")
@click.option(
    "--browser",
    type=click.Choice([*BROWSERS, "all"]),
    default="all",
    show_default=True,
)
@click.option(
    "--host-path",
    type=click.Path(path_type=Path),
    default=None,
    help="The dynomark-host executable (default: the installed one).",
)
def install_host_manifest(
    extension_id: str, browser: str, host_path: Path | None
) -> None:
    """Write the tds.dynomark native-messaging host manifest."""
    browsers = BROWSERS if browser == "all" else (browser,)
    try:
        written = install_manifests(
            host_path or _installed("dynomark-host"),
            extension_id,
            platform=sys.platform,
            home=Path.home(),
            browsers=browsers,
        )
    except InvalidExtensionId as error:
        raise click.BadParameter(str(error), param_hint="--extension-id") from error
    except FileNotFoundError as error:
        raise click.ClickException(str(error)) from error
    for path in written:
        click.echo(str(path))


@main.command("launchd-plist")
@click.option(
    "--program",
    type=click.Path(path_type=Path),
    default=None,
    help="The dynomark-daemon executable (default: the installed one).",
)
def launchd_plist_command(program: Path | None) -> None:
    """Print a user LaunchAgent plist that runs `dynomark-daemon serve`.

    Refuses (exit 1) when the daemon it starts would listen on another socket
    than the one dynomark-host, started by the browser without this shell's
    environment, connects to."""
    settings = _settings(os.environ)
    home = Path.home()
    daemon_env = passed_env(os.environ)
    listens = _settings(daemon_env).socket_path
    connects = host_socket_path({}, home=home)
    if listens != connects:
        raise click.ClickException(
            f"the daemon would listen on {listens}, but dynomark-host, which "
            f"the browser starts without this shell's environment, connects "
            f"to {connects}. Name the socket in {config_path({}, home=home)} "
            f'([socket] path = "..."), the config file the host reads, and '
            f"run launchd-plist again from a shell whose XDG_CONFIG_HOME, "
            f"XDG_STATE_HOME and DYNOMARK_SOCKET do not point elsewhere."
        )
    plist = launchd_plist(
        program or _installed("dynomark-daemon"), settings, os.environ
    )
    click.echo(plist.decode("utf-8"), nl=False)
