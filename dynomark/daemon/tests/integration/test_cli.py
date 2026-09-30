"""``dynomark-daemon``: serve, check, install-host-manifest, launchd-plist
(task-025 item 7). Through Click's runner with a temporary home; Ollama is
a local fake on 127.0.0.1 or a closed port.
"""

import plistlib
import socket
import stat
from pathlib import Path

import pytest
from click.testing import CliRunner

from dynomark_daemon.adapters.sqlite_store import SqliteCorpusStore
from dynomark_daemon.cli import main
from tests._fake_ollama import Script, fake_ollama
from tests._server import build_server, running

pytestmark = pytest.mark.integration

EXTENSION = "abcdefghijklmnopabcdefghijklmnop"


def _closed_port() -> str:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return f"http://127.0.0.1:{port}"


def _env(home: Path, ollama: str) -> dict[str, str]:
    return {
        "HOME": str(home),
        "XDG_STATE_HOME": str(home / "state"),
        "XDG_CONFIG_HOME": str(home / "config"),
        "DYNOMARK_SOCKET": str(home / "d.sock"),
        "OLLAMA_HOST": ollama,
    }


def _lines(output: str) -> dict[str, str]:
    return {line.split()[0]: line for line in output.splitlines() if line.strip()}


def test_check_on_a_fresh_install_without_ollama_reports_and_touches_nothing(
    tmp_path: Path,
) -> None:
    """Given no config, no store, no daemon and no Ollama, When check runs, Then
    it reports the reader defaults, the absent store and socket, Ollama
    unreachable, exits 1, and creates no file."""
    result = CliRunner().invoke(main, ["check"], env=_env(tmp_path, _closed_port()))

    lines = _lines(result.output)
    assert result.exit_code == 1, result.output
    assert "reader" in lines["role"] and "defaults" in lines["config"]
    assert "absent" in lines["store"] and "not listening" in lines["socket"]
    assert "FAIL" in lines["ollama"]
    assert sorted(p.name for p in tmp_path.iterdir()) == []


def test_check_is_green_when_everything_is_in_place(tmp_path: Path) -> None:
    """Given a config, a store, a daemon listening and Ollama with both models,
    When check runs, Then every line is ok and it exits 0."""
    env = _env(tmp_path, "")
    (tmp_path / "config" / "dynomark").mkdir(parents=True)
    (tmp_path / "config" / "dynomark" / "config.toml").write_text('role = "writer"\n')
    SqliteCorpusStore.open(tmp_path / "state" / "dynomark" / "corpus.sqlite3").close()
    script = Script(models=["nomic-embed-text:latest", "llama3.1:8b"])
    with fake_ollama(script) as base, running(build_server(tmp_path / "d.sock")):
        result = CliRunner().invoke(main, ["check"], env={**env, "OLLAMA_HOST": base})

    assert result.exit_code == 0, result.output
    assert "FAIL" not in result.output and "writer" in _lines(result.output)["role"]


def test_check_names_a_model_that_is_not_pulled(tmp_path: Path) -> None:
    """Given Ollama without the completion model, When check runs, Then the
    models line fails naming it."""
    with fake_ollama(Script(models=["nomic-embed-text"])) as base:
        result = CliRunner().invoke(main, ["check"], env=_env(tmp_path, base))

    assert result.exit_code == 1
    assert "llama3.1:8b" in _lines(result.output)["models"]


def test_install_host_manifest_writes_both_browsers_under_home(tmp_path: Path) -> None:
    """Given an extension id and a host path, When install-host-manifest runs,
    Then a manifest per browser is written under HOME and each path printed."""
    host = tmp_path / "dynomark-host"
    host.write_text("#!/bin/sh\n")

    result = CliRunner().invoke(
        main,
        [
            "install-host-manifest",
            "--extension-id",
            EXTENSION,
            "--host-path",
            str(host),
        ],
        env=_env(tmp_path, ""),
    )

    assert result.exit_code == 0, result.output
    written = [
        Path(line) for line in result.output.splitlines() if line.endswith(".json")
    ]
    assert len(written) == 2 and all(p.is_file() for p in written)


def test_install_host_manifest_refuses_a_bad_extension_id(tmp_path: Path) -> None:
    """Given a malformed extension id, When installing, Then it exits non-zero."""
    host = tmp_path / "dynomark-host"
    host.write_text("#!/bin/sh\n")

    result = CliRunner().invoke(
        main,
        ["install-host-manifest", "--extension-id", "nope", "--host-path", str(host)],
        env=_env(tmp_path, ""),
    )

    assert result.exit_code == 2


def _gui_env(home: Path, **shell: str) -> dict[str, str | None]:
    """The installing shell: ``HOME``, Ollama, and only the ``shell`` paths
    named; every other path variable unset (the browser's environment has
    none of them)."""
    unset: dict[str, str | None] = {
        name: None for name in ("XDG_STATE_HOME", "XDG_CONFIG_HOME", "DYNOMARK_SOCKET")
    }
    return {
        **unset,
        "HOME": str(home),
        "OLLAMA_HOST": "http://127.0.0.1:11434",
        **shell,
    }


def _name_socket_in_default_config(home: Path, socket_path: Path) -> None:
    config = home / ".config" / "dynomark"
    config.mkdir(parents=True)
    (config / "config.toml").write_text(f'[socket]\npath = "{socket_path}"\n')


def test_launchd_plist_runs_serve_for_the_user(tmp_path: Path) -> None:
    """Given a program path, When launchd-plist runs, Then it prints a user
    LaunchAgent plist that runs `<program> serve`, at load and kept alive,
    logging to the state directory."""
    result = CliRunner().invoke(
        main,
        ["launchd-plist", "--program", "/opt/bin/dynomark-daemon"],
        env=_gui_env(tmp_path),
    )

    assert result.exit_code == 0, result.output
    plist = plistlib.loads(result.output.encode("utf-8"))
    assert plist["Label"] == "tds.dynomark.daemon"
    assert plist["ProgramArguments"] == ["/opt/bin/dynomark-daemon", "serve"]
    assert plist["RunAtLoad"] is True and plist["KeepAlive"] is True
    assert plist["StandardErrorPath"].startswith(
        str(tmp_path / ".local" / "state" / "dynomark")
    )
    assert plist["EnvironmentVariables"]["OLLAMA_HOST"] == "http://127.0.0.1:11434"


@pytest.mark.parametrize(
    "variable", ["XDG_STATE_HOME", "XDG_CONFIG_HOME", "DYNOMARK_SOCKET"]
)
def test_launchd_plist_refuses_a_socket_the_host_would_not_find(
    tmp_path: Path, variable: str
) -> None:
    """Given the installing shell moves the socket (XDG_STATE_HOME,
    XDG_CONFIG_HOME to a config naming another socket, or DYNOMARK_SOCKET),
    When launchd-plist runs, Then it prints no plist and exits non-zero,
    naming both sockets and telling the user to name the socket in the
    default-location config file: dynomark-host, started by the browser
    without the shell's environment, would connect elsewhere forever."""
    moved = {
        "XDG_STATE_HOME": str(tmp_path / "xdg-state"),
        "XDG_CONFIG_HOME": str(tmp_path / "xdg-config"),
        "DYNOMARK_SOCKET": str(tmp_path / "elsewhere.sock"),
    }[variable]
    other_config = tmp_path / "xdg-config" / "dynomark"
    other_config.mkdir(parents=True)
    (other_config / "config.toml").write_text(
        f'[socket]\npath = "{tmp_path / "xdg.sock"}"\n'
    )
    host_socket = tmp_path / ".local" / "state" / "dynomark" / "daemon.sock"

    result = CliRunner().invoke(
        main,
        ["launchd-plist", "--program", "/opt/bin/dynomark-daemon"],
        env=_gui_env(tmp_path, **{variable: moved}),
    )

    assert result.exit_code != 0
    assert "<plist" not in result.output
    assert str(host_socket) in result.output
    assert str(tmp_path / ".config" / "dynomark" / "config.toml") in result.output
    assert "[socket]" in result.output


def test_launchd_plist_accepts_a_socket_named_in_the_default_config(
    tmp_path: Path,
) -> None:
    """Given the shell sets XDG_STATE_HOME but the default-location config
    names the socket, When launchd-plist runs, Then the daemon it starts and
    the browser's host resolve the same socket, and the plist is printed."""
    _name_socket_in_default_config(tmp_path, tmp_path / "shared.sock")

    result = CliRunner().invoke(
        main,
        ["launchd-plist", "--program", "/opt/bin/dynomark-daemon"],
        env=_gui_env(tmp_path, XDG_STATE_HOME=str(tmp_path / "xdg-state")),
    )

    assert result.exit_code == 0, result.output
    plist = plistlib.loads(result.output.encode("utf-8"))
    assert plist["ProgramArguments"] == ["/opt/bin/dynomark-daemon", "serve"]


def test_serve_with_a_bad_config_exits_2_naming_the_key(tmp_path: Path) -> None:
    """Given a config with an unknown key, When serve runs, Then it exits 2 and
    names the key, having bound nothing."""
    (tmp_path / "config" / "dynomark").mkdir(parents=True)
    (tmp_path / "config" / "dynomark" / "config.toml").write_text('rol = "writer"\n')

    result = CliRunner().invoke(main, ["serve"], env=_env(tmp_path, ""))

    assert result.exit_code == 2 and "rol" in result.output
    assert not (tmp_path / "d.sock").exists()


def test_serve_refuses_a_socket_another_daemon_serves(tmp_path: Path) -> None:
    """Given a daemon already listening, When serve runs, Then it exits 1 saying
    so, and the state directory it made is owner-only."""
    env = _env(tmp_path, "")
    with running(build_server(tmp_path / "d.sock")):
        result = CliRunner().invoke(main, ["serve"], env=env)

    assert result.exit_code == 1 and "already" in result.output
    state = tmp_path / "state" / "dynomark"
    assert stat.S_IMODE(state.stat().st_mode) == 0o700


def test_serve_on_a_socket_path_too_long_exits_1_saying_why(tmp_path: Path) -> None:
    """Given DYNOMARK_SOCKET longer than the OS allows, When serve runs, Then it
    exits 1 with a message naming the socket, not a traceback."""
    env = {**_env(tmp_path, ""), "DYNOMARK_SOCKET": str(tmp_path / ("s" * 120))}

    result = CliRunner().invoke(main, ["serve"], env=env)

    assert result.exit_code == 1
    assert "cannot listen" in result.output and "Traceback" not in result.output
