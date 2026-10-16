"""The native-messaging host manifest (contract/v2/README.md, Endpoint: host
name ``tds.dynomark``; Design, Security Considerations: "the
native-messaging shim is bound to the extension's identity in the host
manifest"). Chrome and Chromium name the extension by origin
(``allowed_origins``), Firefox by its gecko id (``allowed_extensions``;
task-032). Written into a temporary home directory.
"""

import json
from pathlib import Path

import pytest

from dynomark_daemon.adapters.host_manifest import (
    HOST_NAME,
    InvalidExtensionId,
    install_manifests,
    manifest_dirs,
)

pytestmark = pytest.mark.integration

EXTENSION = "abcdefghijklmnopabcdefghijklmnop"
GECKO_ID = "dynomark@tds.dynomark"
MAC_SUPPORT = "Library/Application Support"


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        (
            "darwin",
            {
                "chrome": f"{MAC_SUPPORT}/Google/Chrome/NativeMessagingHosts",
                "chromium": f"{MAC_SUPPORT}/Chromium/NativeMessagingHosts",
                "firefox": f"{MAC_SUPPORT}/Mozilla/NativeMessagingHosts",
            },
        ),
        (
            "linux",
            {
                "chrome": ".config/google-chrome/NativeMessagingHosts",
                "chromium": ".config/chromium/NativeMessagingHosts",
                "firefox": ".mozilla/native-messaging-hosts",
            },
        ),
    ],
)
def test_manifest_dirs_are_the_per_user_directories_of_each_browser(
    platform: str, expected: dict[str, str], tmp_path: Path
) -> None:
    """Given macOS or Linux, When the directories are asked for, Then each is the
    browser's per-user NativeMessagingHosts directory under home."""
    dirs = manifest_dirs(platform, home=tmp_path)

    assert {b: str(p.relative_to(tmp_path)) for b, p in dirs.items()} == expected


def test_install_writes_one_manifest_per_browser_bound_to_the_extension(
    tmp_path: Path,
) -> None:
    """Given a host executable and an extension id, When installed for both
    browsers, Then each directory holds tds.dynomark.json naming the host by
    absolute path, stdio, and only that extension's origin."""
    host = tmp_path / "bin" / "dynomark-host"
    host.parent.mkdir()
    host.write_text("#!/bin/sh\n")

    written = install_manifests(
        host, EXTENSION, platform="linux", home=tmp_path / "home"
    )

    assert len(written) == 2
    for path in written:
        assert path.name == f"{HOST_NAME}.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        assert document == {
            "name": "tds.dynomark",
            "description": "Dynomark: native-messaging pipe to the dynomark daemon",
            "path": str(host.resolve()),
            "type": "stdio",
            "allowed_origins": [f"chrome-extension://{EXTENSION}/"],
        }


@pytest.mark.parametrize(
    "extension_id", ["", "ABCDEFGHIJKLMNOPABCDEFGHIJKLMNOP", "abc", "q" * 32]
)
def test_install_refuses_a_malformed_extension_id(
    extension_id: str, tmp_path: Path
) -> None:
    """Given an id that is not 32 letters a-p, When installing, Then it raises
    and writes nothing (the manifest must name exactly one extension)."""
    with pytest.raises(InvalidExtensionId):
        install_manifests(
            tmp_path / "dynomark-host", extension_id, platform="linux", home=tmp_path
        )

    assert not any(tmp_path.rglob("*.json"))


def test_install_refuses_a_host_path_that_does_not_exist(tmp_path: Path) -> None:
    """Given no executable at the host path, When installing, Then it raises
    FileNotFoundError and writes nothing."""
    with pytest.raises(FileNotFoundError):
        install_manifests(
            tmp_path / "missing", EXTENSION, platform="darwin", home=tmp_path
        )

    assert not any(tmp_path.rglob("*.json"))


def _host(tmp_path: Path) -> Path:
    host = tmp_path / "bin" / "dynomark-host"
    host.parent.mkdir()
    host.write_text("#!/bin/sh\n")
    return host


def test_install_for_firefox_binds_the_gecko_id_in_allowed_extensions(
    tmp_path: Path,
) -> None:
    """Given a gecko id, When installed for Firefox, Then Firefox's per-user
    directory holds tds.dynomark.json naming the host by absolute path, stdio,
    and only that extension in allowed_extensions (Firefox ignores
    allowed_origins and refuses a host whose manifest lacks the id)."""
    host = _host(tmp_path)
    home = tmp_path / "home"

    written = install_manifests(
        host, GECKO_ID, platform="linux", home=home, browsers=("firefox",)
    )

    assert written == [home / ".mozilla/native-messaging-hosts/tds.dynomark.json"]
    assert json.loads(written[0].read_text(encoding="utf-8")) == {
        "name": "tds.dynomark",
        "description": "Dynomark: native-messaging pipe to the dynomark daemon",
        "path": str(host.resolve()),
        "type": "stdio",
        "allowed_extensions": [GECKO_ID],
    }


@pytest.mark.parametrize(
    ("extension_id", "browsers"),
    [
        (EXTENSION, ("chrome", "chromium")),
        (GECKO_ID, ("firefox",)),
        ("{0f8a7e2c-3b4d-4e5f-8a9b-0c1d2e3f4a5b}", ("firefox",)),
    ],
)
def test_install_with_no_browser_named_writes_every_browser_the_id_fits(
    extension_id: str, browsers: tuple[str, ...], tmp_path: Path
) -> None:
    """Given a Chrome id or a gecko id (address or braced uuid) and no browser
    named, When installed, Then exactly the browsers whose extension ids take
    that form get a manifest: an id names an extension in one family only."""
    home = tmp_path / "home"

    written = install_manifests(
        _host(tmp_path), extension_id, platform="darwin", home=home
    )

    dirs = manifest_dirs("darwin", home=home)
    assert written == [dirs[b] / f"{HOST_NAME}.json" for b in browsers]


@pytest.mark.parametrize(
    ("extension_id", "browser"),
    [
        (GECKO_ID, "chrome"),
        (GECKO_ID, "chromium"),
        (EXTENSION, "firefox"),
        ("dynomark", "firefox"),
        ("dynomark@tds dynomark", "firefox"),
        ("{0f8a7e2c-3b4d}", "firefox"),
        ("a" * 80 + "@tds.dynomark", "firefox"),
    ],
)
def test_install_refuses_an_id_the_named_browser_cannot_hold(
    extension_id: str, browser: str, tmp_path: Path
) -> None:
    """Given an id that is not the named browser's extension-id form (a gecko
    id for Chrome, a Chrome id or a malformed or over-long gecko id for
    Firefox), When installing for that browser, Then it raises and writes
    nothing."""
    with pytest.raises(InvalidExtensionId):
        install_manifests(
            _host(tmp_path),
            extension_id,
            platform="linux",
            home=tmp_path / "home",
            browsers=(browser,),
        )

    assert not any(tmp_path.rglob("*.json"))
