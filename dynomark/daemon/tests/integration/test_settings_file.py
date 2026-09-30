"""Reading $XDG_CONFIG_HOME/dynomark/config.toml from disk (a temp home)."""

from pathlib import Path

import pytest

from dynomark_daemon.domain.roles import HostRole
from dynomark_daemon.settings import ConfigError, load_settings

pytestmark = pytest.mark.integration


def test_load_settings_reads_the_config_file_under_the_config_home(
    tmp_path: Path,
) -> None:
    """Given config.toml under XDG_CONFIG_HOME/dynomark, When settings load, Then
    its values are used and the file is named as found."""
    config_dir = tmp_path / "config" / "dynomark"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text('role = "writer"\nhost_id = "mbp"\n')
    env = {"XDG_CONFIG_HOME": str(tmp_path / "config")}

    settings = load_settings(env, home=tmp_path, hostname="x")

    assert settings.config.role is HostRole.WRITER
    assert settings.config_path == config_dir / "config.toml" and settings.config_found


def test_load_settings_without_a_file_uses_the_defaults(tmp_path: Path) -> None:
    """Given no config file, When settings load, Then the reader defaults apply
    and nothing is created."""
    settings = load_settings({}, home=tmp_path, hostname="x")

    assert settings.config.role is HostRole.READER
    assert not any(tmp_path.iterdir())


def test_load_settings_of_invalid_toml_is_a_config_error(tmp_path: Path) -> None:
    """Given a config file that is not TOML, When settings load, Then
    ConfigError names the file."""
    config_dir = tmp_path / ".config" / "dynomark"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text("role = \n")

    with pytest.raises(ConfigError, match="config.toml"):
        load_settings({}, home=tmp_path, hostname="x")
